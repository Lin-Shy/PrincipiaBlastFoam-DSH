"""恢复14B逐项评分的网络缺口；直接HTTPS到同一API，已收到响应仅重放。"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import copy
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
import urllib.request


def status(revision, state, **kwargs):
    path = revision / "STATUS.json"
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps({"state": state, "pid": os.getpid(), "updated_unix": time.time(), **kwargs}, ensure_ascii=False, indent=2)+"\n")
    temp.replace(path)


def clean_stability(core, root, view):
    sample = set(core.load(root / "evaluation_only/review-sample.json")["families"])
    questions = core.load(Path(core.load(root / "protocol.json")["inputs"]["test_questions"]["path"]))
    counts = {"planned": 0, "answer_failed_or_empty": 0, "invalid_item_pairs": 0,
              "schema_valid_pairs": 0, "uncertain_label_pairs": 0, "determinate_pairs": 0, "same_determinate_labels": 0}
    for q in questions:
        if q["family_id"] not in sample:
            continue
        for repeat in range(1, 4):
            for arm in core.ARMS:
                counts["planned"] += 1
                suffix = Path("test") / q["id"] / f"r{repeat}" / arm / "score.json"
                left, right = [core.load(view / "evaluation_only" / stage / suffix) for stage in ("scores", "regrades")]
                if any(x["judgment"] is None for x in (left, right)):
                    counts["answer_failed_or_empty"] += 1
                    continue
                if any(not i["valid"] for x in (left, right) for i in x["atomic_items"]):
                    counts["invalid_item_pairs"] += 1
                    continue
                counts["schema_valid_pairs"] += 1
                unknown = any(x["judgment"]["extra_errors_uncertain"] or
                              any(i["assessment"] == "uncertain" for i in x["judgment"]["requirements"]) or
                              any(i["support"] == "uncertain" for i in x["judgment"]["citations"]) for x in (left, right))
                if unknown:
                    counts["uncertain_label_pairs"] += 1
                    continue
                counts["determinate_pairs"] += 1
                labels = lambda x: ([i["assessment"] for i in x["judgment"]["requirements"]],
                                    [i["support"] for i in x["judgment"]["citations"]], bool(x["judgment"]["extra_errors"]))
                counts["same_determinate_labels"] += labels(left) == labels(right)
    counts["determinate_agreement"] = counts["same_determinate_labels"] / counts["determinate_pairs"] if counts["determinate_pairs"] else None
    counts["limits"] = "conditional on schema-valid determinate judgments; full fixed denominator retained above; not human truth"
    return counts


def prepare(core, root, parent, revision, exporter, guard):
    if revision.exists():
        raise FileExistsError("new atomic transport recovery archive required")
    revision.mkdir(parents=True)
    runtime = revision / "runtime"
    runtime.mkdir()
    for source in (Path(__file__), exporter, guard):
        shutil.copyfile(source, runtime / source.name)
        (runtime / source.name).chmod(0o444)
    targets = []
    view = revision / "canonical_view"
    (view / "evaluation_only").mkdir(parents=True)
    for name in ("protocol.json", "runs"):
        (view / name).symlink_to(root / name)
    for name in ("dev.annotations.json", "test.annotations.json", "review-sample.json"):
        (view / "evaluation_only" / name).symlink_to(root / "evaluation_only" / name)
    (view / "reports").mkdir()
    for split in ("dev", "test"):
        (view / "reports" / f"{split}-mechanism-report.json").symlink_to(root / "reports" / f"{split}-mechanism-report.json")
    for stage in ("scores", "regrades"):
        for original in sorted((parent / stage).rglob("score.json")):
            record = core.load(original)
            positions = [i for i, item in enumerate(record["atomic_items"]) if item["error"] == "atomic_judge_transport_exhausted"]
            relative = original.relative_to(parent / stage)
            link = view / "evaluation_only" / stage / relative
            link.parent.mkdir(parents=True, exist_ok=True)
            if positions:
                targets.append({"stage": stage, "relative": str(relative), "positions": positions, "original_sha256": core.sha(original)})
                link.symlink_to(revision / stage / relative)
            else:
                link.symlink_to(original)
    spec = {"schema": "atomic-same-request-direct-https-recovery-v1", "date": "2026-10-12",
            "parent_protocol_sha256": core.sha(root / "protocol.json"), "parent_scoring_protocol_sha256": core.sha(parent / "protocol.json"),
            "parent": str(parent), "judge_model": "qwen3-14b", "generator_model": "qwen3-8b",
            "registration": "transport amendment after first full 14B grading; not original preregistered execution",
            "targets": targets, "network_items": sum(len(t["positions"]) for t in targets), "workers": 3,
            "direct_https": True, "endpoint_unchanged": True, "tls_verification_unchanged": True,
            "additional_transport_attempts_per_failed_request": 3, "maximum_original_plus_recovery_attempts": 6,
            "max_schema_attempts_unchanged": 2, "quality_retry": False,
            "circuit": "halt scheduling after first exhausted recovery item; preserve partial outputs"}
    core.save(revision / "protocol.json", spec)
    core.save(revision / "seal.json", {"protocol_sha256": core.sha(revision / "protocol.json"),
                                     "runtime": {p.name: core.sha(p) for p in runtime.iterdir()}})
    print(core.wire({"targets": len(targets), "network_items": spec["network_items"], "api_calls": 0}))


def run(core, evaluation, root, revision, plot_python):
    core.verify(root)
    spec = core.load(revision / "protocol.json")
    seal = core.load(revision / "seal.json")
    if seal["protocol_sha256"] != core.sha(revision / "protocol.json"):
        raise ValueError("atomic recovery protocol drift")
    for name, digest in seal["runtime"].items():
        if core.sha(revision / "runtime" / name) != digest:
            raise ValueError("atomic recovery runtime drift")
    parent = Path(spec["parent"])
    if core.sha(parent / "protocol.json") != spec["parent_scoring_protocol_sha256"]:
        raise ValueError("parent scorer drift")
    parent_seal = core.load(parent / "seal.json")
    grader_path = parent / "runtime/chapter2_atomic_judge.py"
    if core.sha(grader_path) != parent_seal["script_sha256"]:
        raise ValueError("parent grading function drift")
    module_spec = importlib.util.spec_from_file_location("frozen_atomic", grader_path)
    atomic = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(atomic)
    atomic.configure_judge(core, parent)
    sys.path.insert(0, str(revision / "runtime"))
    from chapter2_connection_guard import guarded_open
    direct = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    urllib.request.urlopen = guarded_open(direct.open, revision / "connection_exception_events")
    provider = core.Provider(root, root / "local_private/.env.qwen_proxy")
    circuit = threading.Event()
    with (revision / "campaign.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        status(revision, "running", phase="direct_https_health")
        req = core.request([{"role": "system", "content": '只输出JSON {"ok":true}。'}, {"role": "user", "content": "验证连接。"}], "grep", final=True, output_tokens=30)
        req["model"] = "qwen3-14b"
        raw = provider(req, revision / "health", "probe")
        core.usage(raw)
        if json.loads(raw["choices"][0]["message"]["content"]) != {"ok": True}:
            raise RuntimeError("direct HTTPS probe failed")
        status(revision, "running", phase="restore_network_items", targets=len(spec["targets"]), items=spec["network_items"])

        def one(target):
            stage, relative = target["stage"], Path(target["relative"])
            output = revision / stage / relative
            if output.exists():
                if core.load(output)["atomic_transport_recovery_sha256"] != seal["protocol_sha256"]:
                    raise ValueError("recovered score drift")
                return
            if circuit.is_set():
                raise RuntimeError("atomic transport circuit open")
            original = parent / stage / relative
            if core.sha(original) != target["original_sha256"]:
                raise ValueError("original atomic score drift")
            checkpoint = revision / "checkpoints" / stage / relative
            record = core.load(checkpoint) if checkpoint.exists() else copy.deepcopy(core.load(original))
            completed = set(record.get("network_recovery_completed_positions", []))
            if checkpoint.exists() and record["atomic_transport_recovery_sha256"] != seal["protocol_sha256"]:
                raise ValueError("recovery checkpoint drift")
            split, qid, repeat, arm = relative.parts[:4]
            session_path = root / "runs" / split / qid / repeat / arm / "session.json"
            session = core.load(session_path)
            claims = [{"index": i, "text": c["text"]} for i, c in enumerate(session["answer"]["claims"])]
            for position in target["positions"]:
                if circuit.is_set():
                    break
                if position in completed:
                    continue
                item = record["atomic_items"][position]
                kind = item["kind"]
                prefix = f"{kind}-{item['index']:02d}" if kind != "extra" else "extra"
                first_request = core.load(original.parent / (prefix + "-0.attempt-0.json"))["request"]
                packet = json.loads(first_request["messages"][1]["content"])
                prompt = first_request["messages"][0]["content"]

                def fetch(req, folder, label):
                    old_response = original.parent / (label + ".json")
                    if old_response.exists():
                        return provider(req, original.parent, label)
                    old_attempt = original.parent / (label + ".attempt-0.json")
                    if old_attempt.exists():
                        import hashlib
                        if hashlib.sha256(core.wire(req).encode()).hexdigest() != core.load(old_attempt)["request_sha256"]:
                            raise ValueError("restored atomic request differs from original")
                    try:
                        return provider(req, folder, label)
                    except core.TransportFailure:
                        circuit.set()
                        raise

                value, error = atomic.judge_item(core, fetch, output.parent, prefix, prompt, packet, kind, claims)
                item.update(valid=value is not None, error=error, judgment=value)
                judgment = record["judgment"]
                if kind == "fact":
                    judgment["requirements"][item["index"]] = {"index": item["index"], "assessment": value["assessment"] if value else "uncertain",
                        "actual_answer_quote": value["actual_answer_quote"] if value else "", "reason": value["reason"] if value else error}
                elif kind == "citation":
                    judgment["citations"][item["index"]] = {"index": item["index"], "support": value["support"] if value else "uncertain", "reason": value["reason"] if value else error}
                else:
                    judgment["extra_errors"] = [claims[i]["text"] for i in value["error_claim_indices"]] if value else []
                    judgment["extra_errors_uncertain"] = value["uncertain"] if value else True
                completed.add(position)
                record["network_recovery_completed_positions"] = sorted(completed)
                record["atomic_transport_recovery_sha256"] = seal["protocol_sha256"]
                checkpoint.parent.mkdir(parents=True, exist_ok=True)
                temp = checkpoint.with_suffix(".tmp")
                temp.write_text(core.wire(record)+"\n")
                temp.replace(checkpoint)
            if completed != set(target["positions"]):
                raise RuntimeError("atomic transport circuit open; partial checkpoint preserved")
            record["status"] = "scored" if all(i["valid"] for i in record["atomic_items"]) else "partial_unknown"
            record["bounds"] = evaluation.semantic_bounds(record["judgment"], len(record["judgment"]["requirements"]))
            record["atomic_transport_recovery_sha256"] = seal["protocol_sha256"]
            record["original_score_sha256"] = target["original_sha256"]
            core.save(output, record)
            print(core.wire({"stage": stage, "split": split, "question": qid, "repeat": repeat, "arm": arm, "status": record["status"]}), flush=True)

        with ThreadPoolExecutor(max_workers=spec["workers"]) as pool:
            list(pool.map(one, spec["targets"]))
        if circuit.is_set():
            raise RuntimeError("atomic network recovery exhausted")
        for split in ("dev", "test"):
            report = evaluation.report(revision / "canonical_view", core.load(root / "protocol.json"), split)
            report["evaluation_revision"] = {"protocol": str(parent / "protocol.json"), "sha256": spec["parent_scoring_protocol_sha256"],
                                             "judge_model": "qwen3-14b", "registration": core.load(parent / "protocol.json")["registration"]}
            report["transport_recovery"] = {"protocol": str(revision / "protocol.json"), "sha256": seal["protocol_sha256"], "judge_model": "qwen3-14b"}
            report["limits"] = "generator 8B/judge 14B; direct-HTTPS same-request recovery; original scores retained; not preregistered original judge or independent truth"
            for arm in core.ARMS:
                rows = [r for r in report["rows"] if r["arm"] == arm]
                report["summary"][arm]["unknown_scores"] = sum(r["score_status"] == "partial_unknown" or
                    any(r["bounds"][metric][0] != r["bounds"][metric][1] for metric in ("fact_coverage", "answer_complete")) for r in rows)
            report["scoring_stability"]["limits"] = "includes fallback uncertainty labels; determinate-pair agreement needs separate audit; not independent truth"
            if split == "test":
                report["clean_scoring_stability"] = clean_stability(core, root, revision / "canonical_view")
            core.save(revision / "canonical_view/reports" / f"{split}-report.json", report)
            with (revision / f"{split}_export.log").open("a") as log:
                result = subprocess.run([str(plot_python.absolute()), str(revision / "runtime/build_report.py"), "--root", str(revision / "canonical_view"),
                                         "--split", split, "--output", str(revision / "derived/exports_001" / split)], stdout=log, stderr=subprocess.STDOUT,
                                         env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
            if result.returncode:
                raise RuntimeError("direct recovery export failed")
        status(revision, "complete", phase="finished", items=spec["network_items"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "run"))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--parent", type=Path)
    parser.add_argument("--revision", type=Path, required=True)
    parser.add_argument("--exporter", type=Path)
    parser.add_argument("--guard", type=Path)
    parser.add_argument("--plot-python", type=Path)
    args = parser.parse_args()
    root, revision = args.root.resolve(), args.revision.resolve()
    sys.path.insert(0, str(root / "runtime"))
    import chapter2_augmentation as core
    import chapter2_augmentation_evaluation as evaluation
    if args.command == "prepare":
        if not all((args.parent, args.exporter, args.guard)):
            parser.error("prepare requires parent/exporter/guard")
        prepare(core, root, args.parent.resolve(), revision, args.exporter, args.guard)
    else:
        if Path(__file__).resolve() != revision / "runtime" / Path(__file__).name or not args.plot_python:
            raise ValueError("execute archived atomic transport recovery")
        try:
            run(core, evaluation, root, revision, args.plot_python)
        except Exception as exc:
            status(revision, "failed", phase="see_campaign_log", error_type=type(exc).__name__)
            raise


if __name__ == "__main__":
    main()
