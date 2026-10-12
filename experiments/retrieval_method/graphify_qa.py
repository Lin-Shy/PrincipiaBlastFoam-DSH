"""同一725文件语料上的五臂Graphify基线问答；不重建图，不读取金标准作答。"""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import fcntl
import json
import os
from pathlib import Path
import random
import shutil
import sys
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import navigation_qa as qa
from graphify_query_backend import Backend, bounded_payload, original_paths

GRAPH = """附加工具locate: {action:"locate",translation:"可选忠实英文表达",query:"可选后续证据缺口",reason:"..."}。
locate始终把完整原始问题与所给补充送入固定Graphify，返回文件/概念/图关系导航，不自动读取原文。
src字段已还原为原文路径，可交给source；不要把节点标签或EXTRACTED当作已核验的原文，必须用原文支持答案。
图可能遗漏文件、缺少来源、包含未核验关联。truncated表示输出被公共字符预算裁剪；可补充查询，但原问题仍保留。
"""
GROUPS = {"control": ["no_graph"], "native": ["graph_optional", "graph_first"],
          "text_adapter": ["graph_optional", "graph_first"]}
SECRET = ""
BASE_WRITE = qa.write
BASE_SESSION = qa.Session
TRANSPORT_OUTAGE_THRESHOLD = 4
_transport_lock = threading.Lock()
_transport_failures = 0
_transport_circuit = threading.Event()


class GlobalTransportOutage(RuntimeError):
    """The process lost network transport; stop the batch before exhausting every frozen request."""


def reset_transport_circuit():
    """Start a fresh process/run attempt with a closed circuit."""
    global _transport_failures
    with _transport_lock:
        _transport_failures = 0
        _transport_circuit.clear()


def _note_transport_result(error=None):
    global _transport_failures
    with _transport_lock:
        if error is None:
            _transport_failures = 0
        elif getattr(error, "code", None) is None:
            _transport_failures += 1
            if _transport_failures >= TRANSPORT_OUTAGE_THRESHOLD:
                _transport_circuit.set()
        else:
            _transport_failures = 0
        return _transport_circuit.is_set()


def runtime_identity():
    return {"pythonhashseed": os.environ.get("PYTHONHASHSEED"),
            "hash_probe": hash("Principia Graphify QA frozen seed"), "python": sys.version}


def verify_runtime(protocol):
    actual = runtime_identity()
    if actual["pythonhashseed"] != "0" or actual != protocol["runtime_identity"]:
        raise ValueError("Run/replay requires the frozen interpreter and PYTHONHASHSEED=0 set before interpreter startup")


def save(path, value):
    if SECRET:
        value = json.loads(qa.wire(value).replace(SECRET, "[REDACTED]"))
    BASE_WRITE(path, value)


def prompt(method):
    common = qa.COMMON.replace("列出原始文件", "列出全部原始文件（含不可读图片/二进制标记）")
    return common + (GRAPH if method != "no_graph" else "") + (qa.FIRST if method == "graph_first" else "")


def fetch(folder, name, body, key):
    """先落盘每次尝试；中断后不把未知消耗变成零，也不按答案质量重试。"""
    path = folder / (name + ".json")
    identity = qa.digest(qa.wire(body))
    old = qa.read(path) if path.exists() else None
    if old:
        if old["request_sha256"] != identity:
            raise ValueError("request changed on resume/replay")
        if old["status"] == "response":
            return old
        if old["status"] not in {"transport_error", "in_flight"}:
            raise ValueError("received invalid response frozen; no quality retry")
    if key is None:
        raise ValueError("successful frozen response missing")
    if _transport_circuit.is_set():
        raise GlobalTransportOutage("global transport outage circuit open; resume in a fresh process")
    events = list(old.get("events", [])) if old else []
    # The process-wide OS lock guarantees another runner is not still sending
    # this request. In-flight recovery is only possible after its process exits.
    for event in events:
        if event["status"] == "in_flight":
            event.update(status="interrupted_unresolved", seconds=None, usage=None)
    if len(events) >= 9:
        raise RuntimeError("maximum nine transport attempts exhausted; preserved")
    record = {"status": "in_flight", "request": body, "request_sha256": identity, "events": events}
    for _ in range(min(3, 9-len(events))):
        if _transport_circuit.is_set():
            raise GlobalTransportOutage("global transport outage circuit open; resume in a fresh process")
        begin = time.monotonic()
        record["status"] = "in_flight"
        event = {"status": "in_flight", "started_unix_ns": time.time_ns(), "seconds": None, "usage": None}
        events.append(event)
        save(path, record)
        try:
            request = Request(qa.ENDPOINT, data=qa.wire(body).encode(), headers={
                "Authorization": "Bearer " + key, "Content-Type": "application/json"})
            # Long Flash answers regularly exceed one minute before headers.
            # Match the already validated Graphify construction transport limit.
            with urlopen(request, timeout=180) as response:
                raw = response.read().decode()
            event.update(status="response", seconds=time.monotonic()-begin)
            try:
                payload = json.loads(raw)
                record.update(status="response", raw_response=payload)
                event["usage"] = payload.get("usage") if isinstance(payload, dict) else None
            except ValueError:
                record.update(status="invalid_response", raw_text=raw)
            save(path, record)
            if record["status"] != "response":
                raise RuntimeError("invalid response saved; terminal")
            _note_transport_result()
            return record
        except (HTTPError, URLError, TimeoutError, OSError) as error:
            event.update(status="transport_error", type=type(error).__name__,
                         http_status=getattr(error, "code", None), seconds=time.monotonic()-begin)
            record["status"] = "transport_error"
            save(path, record)
            if getattr(error, "code", None) in {400, 401, 402, 403}:
                break
            if _note_transport_result(error):
                raise GlobalTransportOutage("global transport outage circuit opened; resume in a fresh process")
    raise RuntimeError("transport_error; only identical-request resume permitted")


class Engine(qa.Engine):
    def __init__(self, run, variant):
        super().__init__(run)
        self.variant = variant
        self.inventory = qa.read(run / "all-files.json")
        self.inverse = qa.read(run / "path-map.json")
        self.backend = None


class Session(BASE_SESSION):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.graph_attempted = False
        self.graph_audits = []

    def dispatch(self, action, cap):
        name = action.get("action")
        if name not in {"catalog", "locate"}:
            return super().dispatch(action, cap)
        if name == "locate" and self.method == "no_graph":
            return super().dispatch(action, cap)
        begin = time.monotonic()
        identity = qa.wire({k: v for k, v in action.items() if k != "reason"})
        repeat = identity in self.seen_requests
        self.seen_requests.add(identity)
        self.calls[name] += 1
        meter = Counter()
        initialization = None
        query_audit = None
        try:
            if name == "catalog":
                query, offset = action.get("query", ""), action.get("offset", 0)
                if not isinstance(query, str) or type(offset) is not int or offset < 0:
                    raise ValueError("invalid catalog query/offset")
                meter["catalog_scanned_characters"] = sum(len(p) for p in self.e.inventory)
                items = [{"path": p, "lines": len(self.e.files[p]) if p in self.e.files else None,
                          "readable_text": p in self.e.files} for p in self.e.inventory if query.casefold() in p.casefold()]
                result = self.pack(items, offset, cap)
            else:
                self.graph_attempted = True
                translation, gap = action.get("translation", ""), action.get("query", "")
                if cap < 1000 or not isinstance(translation, str) or not isinstance(gap, str):
                    raise ValueError("invalid graph query or insufficient remaining budget")
                query = "\n".join(x for x in (self.question, translation, gap) if x)
                if len(query) > 12000:
                    raise ValueError("graph query too long")
                with self.e.graph_lock:
                    if self.e.backend is None:
                        started = time.monotonic()
                        self.e.backend = Backend(self.e.run / "graphify-out/graph.json")
                        initialization = self.e.backend.initialization
                        initialization["seconds"] = time.monotonic() - started
                        save(self.e.run / ("runtime-initialization-" + str(time.time_ns()) + ".json"), initialization)
                    native_budget = max(100, (cap-250)//4)
                    raw, native_cost = self.e.backend.query(query, native_budget)
                restored = original_paths(raw, self.e.inverse)
                meter.update(native_cost["content"])
                meter["graph_path_mapping_input_characters"] += len(raw)
                meter["graph_path_mapping_output_characters"] += len(restored)
                result = bounded_payload(restored, cap, qa.wire)
                self.graph_audits.append({"query": query, "token_budget": native_budget,
                    "raw_native_return": raw, "restored_return": restored,
                    "native_cost": native_cost, "transport_truncated": result["truncated"]})
                query_audit = self.graph_audits[-1]
        except (KeyError, ValueError, TypeError, AttributeError) as error:
            result = {"status": "tool_error", "reason": str(error)[:200]}
        if len(qa.wire(result)) > cap:
            raise AssertionError("tool budget exceeded")
        # Navigation text intentionally adds zero seen original lines.
        self.observe(result)
        return result, {"seconds": time.monotonic()-begin, "repeat": repeat, "content": dict(meter),
                        "initialization": initialization, "initialization_time_included": initialization is not None,
                        "native_query_audit": query_audit}


def install():
    qa.Session, qa.prompt, qa.fetch, qa.write = Session, prompt, fetch, save
    qa.instrument_file_reads()


def run_one(engine, question, method, key, replicate, replay):
    folder = engine.run / "sessions" / f"{question['id']}--{method}--r{replicate}"
    started = time.time_ns()
    path = folder / "invocations" / f"{started}.json"
    state = {"status": "in_flight", "replay": replay, "started_unix_ns": started,
             "elapsed_seconds": None, "arm": engine.variant}
    save(path, state)
    begin = time.monotonic()
    try:
        result = qa._run_one(engine, question, method, key, replicate, replay)
        state["status"] = result["status"]
        return result
    except BaseException:
        state["status"] = "error"
        raise
    finally:
        state["elapsed_seconds"] = time.monotonic()-begin
        save(path, state)


def prepare(args):
    if os.environ.get("PYTHONHASHSEED") != "0":
        raise ValueError("Freeze with PYTHONHASHSEED=0 before interpreter startup")
    archive, run, dataset = args.archive.resolve(), args.run.resolve(), args.dataset.resolve()
    if run.exists():
        raise FileExistsError("Preserve existing experiment; choose a new run")
    # Validate all parent dataset artifact hashes but do not load holdout contents.
    parent = qa.read(dataset / "manifest.json")
    for name, expected in parent["artifacts"].items():
        if qa.digest((dataset / name).read_bytes()) != expected:
            raise ValueError("Parent dataset changed: " + name)
    if args.split != "dev":
        raise ValueError("This baseline development phase does not unlock the holdout")
    corpus = qa.read(archive / "corpus_manifest.json")
    identity = qa.read(archive / "upstream_identity.json")
    graphs = {}
    for variant in ("native", "text_adapter"):
        summary = qa.read(archive / variant / "baseline_summary.json")
        path = archive / variant / "graphify-out/graph.json"
        if qa.digest(path.read_bytes()) != summary["artifacts"]["graph.json"]["sha256"]:
            raise ValueError("Frozen graph changed")
        graphs[variant] = summary["baseline_id"]
    rows = corpus["files"]
    manifest = {}
    for row in rows:
        raw = (archive / "corpus_native" / row["path"]).read_bytes()
        if qa.digest(raw) != row["sha256"]:
            raise ValueError("Frozen source changed")
        if row["utf8_text"]:
            manifest[row["path"]] = {"sha256": row["sha256"], "bytes": len(raw),
                                      "lines": len(raw.decode("utf-8").splitlines())}
    annotations = qa.read(dataset / "dev.annotations.json")
    for annotation in annotations:
        for evidence in annotation["evidence"]:
            raw = (archive / "corpus_native" / evidence["path"]).read_bytes()
            lines = raw.decode("utf-8").splitlines()
            if qa.digest(raw) != evidence["sha256"] or "\n".join(lines[evidence["start"]-1:evidence["end"]]) != evidence["quote"]:
                raise ValueError("Gold evidence no longer matches original corpus")
    run.mkdir(parents=True)
    for name in ("navigation_qa.py", "graphify_query_backend.py", "graphify_qa.py",
                 "navigation_metrics.py", "navigation_review.py"):
        shutil.copy2(Path(__file__).with_name(name), run / ("runner.py" if name == "graphify_qa.py" else name))
    for group, methods in GROUPS.items():
        target = run / group
        shutil.copytree(archive / "corpus_native", target / "skill/corpus")
        shutil.copy2(dataset / "dev.questions.json", target / "questions.json")
        (target / "evaluation_only").mkdir()
        for source, destination in (("dev.annotations.json", "annotations.json"), ("scoring-rules.json", "scoring-rules.json")):
            shutil.copy2(dataset / source, target / "evaluation_only" / destination)
        save(target / "corpus-manifest.json", manifest)
        save(target / "all-files.json", {row["path"]: row for row in rows})
        inverse = {row["path"]: row["path"] for row in rows}
        if group != "control":
            (target / "graphify-out").mkdir()
            shutil.copy2(archive / group / "graphify-out/graph.json", target / "graphify-out/graph.json")
            if group == "text_adapter":
                mapping = qa.read(archive / "text_adapter_manifest.json")["path_map"]
                inverse = {v: k for k, v in mapping.items()}
        save(target / "path-map.json", inverse)
        hashes = {p.relative_to(target).as_posix(): qa.digest(p.read_bytes()) for p in sorted(target.rglob("*")) if p.is_file()}
        save(target / "protocol.json", {"schema": "graphify-navigation-qa-v1", "files": hashes,
            "arm": group, "methods": methods, "model": qa.MODEL, "limits": qa.LIMITS,
            "prompts": {m: prompt(m) for m in methods}, "final": qa.FINAL,
            "replicates": args.replicates, "split": "dev", "graph_baseline": graphs.get(group),
            "dataset_manifest_sha256": qa.digest((dataset / "manifest.json").read_bytes()),
            "corpus_id": corpus["corpus_id"], "text_files": len(manifest), "catalog_files": len(rows),
            "source_scope": "702 readable texts and common 725-entry catalog; no image pixel input in any arm",
            "first_policy": "prompt policy; compliance recorded, no automatic hidden graph calls",
            "graph_query": "original Graphify MCP query core; BFS depth2, native heuristics/default seed selection; transport cap after full native output",
            "graph_evidence": "zero raw source lines credited from graph labels/relationships",
            "failure_policy": "three attempts per invocation, at most nine per identical request; no content/answer-quality retries",
            "quality_status": "unscored; source-grounded review required"})
    frozen = {p.relative_to(run).as_posix(): qa.digest(p.read_bytes()) for p in sorted(run.rglob("*")) if p.is_file()}
    save(run / "protocol.json", {"schema": "graphify-five-arm-qa-v1", "files": frozen,
        "groups": GROUPS, "replicates": args.replicates, "model": qa.MODEL,
        "shuffle_seed": 20260909, "graphify_identity": identity,
        "parent_dataset": str(dataset), "corpus_id": corpus["corpus_id"],
        "scope_revision": "Question wording, splits and gold unchanged; common source scope expanded from 688 to 702 readable texts to match user-requested Graphify input. Old no_graph scores are not reused.",
        "previous_goal_turn": "progress: two actual Graphify builds and their provenance/costs frozen",
        "pre_run_revision": "v3: explicitly freeze process hash seed=0 and interpreter identity for all five arms. v2 preserved as actual pilot evidence: 14/15 strict replay matches, one original Graphify BFS edge-order difference across processes. No query-algorithm, graph, prompt, gold or budget changes.",
        "runtime_identity": runtime_identity(),
        "holdout_unlocked": False, "quality_reviewed": False})
    verify(run)
    print(qa.wire({"prepared": str(run), "text_files": len(manifest), "catalog_files": len(rows),
                   "questions": len(qa.read(run / "control/questions.json")), "groups": GROUPS}))


def verify(run):
    protocol = qa.verify(run)
    import graphify
    package = Path(graphify.__file__).parent
    for path, expected in protocol["graphify_identity"]["implementation_files_sha256"].items():
        if qa.digest((package / path).read_bytes()) != expected:
            raise ValueError("Installed Graphify source changed: " + path)
    return protocol


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["prepare", "verify", "run", "replay"])
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--dataset", type=Path)
    parser.add_argument("--split", default="dev")
    parser.add_argument("--replicates", type=int, default=1)
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--key-file", type=Path)
    parser.add_argument("--only", nargs="*")
    args = parser.parse_args()
    if args.command == "prepare":
        prepare(args)
        return
    run = args.run.resolve()
    protocol = verify(run)
    if args.command == "verify":
        print("frozen corpus, graphs, drivers and Graphify implementation PASS")
        return
    if Path(__file__).resolve() != run / "runner.py":
        raise ValueError("Execute the frozen runner")
    verify_runtime(protocol)
    global SECRET
    SECRET = args.key_file.read_text().strip() if args.key_file else ""
    with (run / "runtime.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        install()
        before_initialization = {str(p) for group in GROUPS for p in (run/group).glob("*-load-*.json")}
        begin_initialization = time.monotonic()
        engines = {group: Engine(run / group, group) for group in GROUPS}
        initialization_seconds = time.monotonic()-begin_initialization
        for group in GROUPS:
            for path in (run/group).glob("raw-corpus-load-*.json"):
                if str(path) not in before_initialization:
                    value = qa.read(path)
                    save(path, {**value, "replay": args.command == "replay", "arm": group})
        questions = qa.read(run / "control/questions.json")
        jobs = [(group, q, method, replicate) for group, methods in GROUPS.items()
                for q in questions if not args.only or q["id"] in args.only
                for method in methods for replicate in range(1, protocol["replicates"]+1)]
        random.Random(protocol["shuffle_seed"]).shuffle(jobs)
        started = time.time_ns()
        journal = run / "invocations" / f"{started}.json"
        state = {"pid": os.getpid(), "state": "running", "started_unix_ns": started,
                 "command": args.command, "selected_questions": args.only, "jobs": len(jobs), "workers": args.workers,
                 "engine_initialization_seconds": initialization_seconds}
        save(journal, state)
        begin = time.monotonic()
        errors, completed = [], 0
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            pending = {}
            for group, question, method, replicate in jobs:
                name = f"{question['id']}--{method}--r{replicate}"
                if args.command == "run" and (run / group / "sessions" / name / "result.json").exists():
                    completed += 1
                    continue
                future = pool.submit(run_one, engines[group], question, method, SECRET or None, replicate, args.command == "replay")
                pending[future] = group + "/" + name
            for future in as_completed(pending):
                try:
                    result = future.result()
                    completed += 1
                    print("DONE", pending[future], result["status"], result["returned_characters"], flush=True)
                except Exception as error:
                    errors.append({"session": pending[future], "error_type": type(error).__name__,
                                   "reason": str(error).replace(SECRET, "[REDACTED]")[:240] if SECRET else str(error)[:240]})
                    print("ERROR", pending[future], type(error).__name__, flush=True)
        verify(run)
        state.update(state="finished", elapsed_seconds=time.monotonic()-begin, completed=completed, errors=errors)
        save(journal, state)
        print(qa.wire({"completed": completed, "requested": len(jobs), "errors": errors}))
        if errors:
            raise SystemExit(1)


if __name__ == "__main__":
    main()
