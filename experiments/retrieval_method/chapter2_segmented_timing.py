"""从原始会话记录导出第2章逐题分段墙钟时间和顺序性能摘要。"""
import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import platform
import statistics


def load(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def percentile(values, p):
    values = sorted(values)
    if not values:
        return None
    rank = (len(values) - 1) * p
    lo, hi = math.floor(rank), math.ceil(rank)
    return values[lo] + (values[hi] - values[lo]) * (rank - lo)


def stage_summary(values):
    return {"completed_samples": len(values), "median_seconds": statistics.median(values) if values else None,
            "p95_seconds": percentile(values, .95)}


def record_for_session(run, session, method, split, mode, concurrency):
    result_path = session / "result.json"
    result = load(result_path) if result_path.exists() else None
    invocations = sorted((session / "invocations").glob("*.json"))
    invocation_rows = [load(p) for p in invocations]
    actual = [r for r in invocation_rows if r.get("replay") is False]
    # A resumed request may create more than one invocation. Use the final
    # successful or failed invocation duration, and retain prior retries.
    end_to_end = actual[-1].get("elapsed_seconds") if actual else None
    search_seconds = 0.0
    search_calls = 0
    answer_seconds = 0.0
    answer_attempts = 0
    failed_attempts = 0
    response_files = set()
    if result:
        for event in result.get("events", []):
            action = event.get("action", {})
            if action.get("action") != "finish" and event.get("accounting"):
                search_seconds += float(event["accounting"].get("seconds", 0))
                search_calls += 1
    # Candidate/E5 sessions also make plan and claim-check requests. Reading
    # every request ledger avoids silently omitting those model calls.
    for path in session.glob("*.json"):
        if path.name == "result.json":
            continue
        payload = load(path)
        if isinstance(payload, dict) and "request_sha256" in payload:
            response_files.add(path.name)
    for name in response_files:
        path = session / name
        if not path.is_file():
            continue
        payload = load(path)
        for event in payload.get("events", []):
            seconds = event.get("seconds")
            if seconds is not None:
                answer_seconds += float(seconds)
                answer_attempts += 1
            if event.get("status") not in ("response", "in_flight"):
                failed_attempts += 1
    if result:
        qid, family, replicate = result["id"], result["item_id"], result["replicate"]
        status = result["status"]
    else:
        parts = session.name.split("--")
        qid, family, replicate = parts[0], None, int(parts[-1].lstrip("r")) if parts[-1].startswith("r") else None
        status = "missing_result"
    return {"run": run.name, "method": method, "split": split, "mode": mode,
            "concurrency": concurrency, "question_id": qid, "family_id": family,
            "replicate": replicate, "status": status,
            "search_seconds": search_seconds if result else None,
            "search_calls": search_calls, "answer_seconds": answer_seconds if response_files else None,
            "answer_attempts": answer_attempts, "failed_answer_attempts": failed_attempts,
            "end_to_end_seconds": end_to_end, "invocations": len(actual),
            "result_sha256": sha(result_path) if result else None}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--runs", type=Path, nargs="+", required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--mode", choices=("quality", "sequential_performance"), required=True)
    p.add_argument("--concurrency", type=int, required=True)
    p.add_argument("--split", choices=("dev", "holdout"), required=True)
    p.add_argument("--method-names", nargs="+", required=True)
    a = p.parse_args()
    if len(a.runs) != len(a.method_names) or a.concurrency < 1:
        raise ValueError("one method per run and positive concurrency required")
    if a.mode == "sequential_performance" and a.concurrency != 1:
        raise ValueError("performance mode requires fixed sequential concurrency 1")
    a.output.mkdir(parents=True, exist_ok=False)
    rows = []
    shared = []
    for run, method in zip(a.runs, a.method_names):
        if not (run / "protocol.json").exists():
            raise ValueError("run lacks frozen protocol: " + str(run))
        for session in sorted((run / "sessions").glob("*")):
            if session.is_dir():
                rows.append(record_for_session(run, session, method, a.split, a.mode, a.concurrency))
        # Cold construction and load are run-level observations. They must not
        # be repeated as if each question incurred them.
        builds = [run / "construction.json", run / "build.json"]
        build = next((load(x) for x in builds if x.exists()), None)
        loads = sorted(run.glob("*initialization*.json")) + sorted(run.glob("raw-corpus-load-*.json"))
        for path in loads:
            obj = load(path)
            shared.append({"run": run.name, "method": method, "kind": "load",
                           "seconds": obj.get("seconds"), "source": str(path), "sha256": sha(path)})
        shared.append({"run": run.name, "method": method, "kind": "build",
                       "seconds": None if method == "no_graph" else (build or {}).get("seconds"),
                       "not_applicable": method == "no_graph", "source": str(next((x for x in builds if x.exists()), "")),
                       "sha256": sha(next(x for x in builds if x.exists())) if build else None})
    (a.output / "per-question.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    (a.output / "build-and-load.json").write_text(json.dumps(shared, ensure_ascii=False, indent=2) + "\n")
    by_method = defaultdict(list)
    for row in rows:
        by_method[row["method"]].append(row)
    report = {"schema": "chapter2-segmented-timing-v1", "mode": a.mode, "split": a.split,
              "concurrency": a.concurrency,
              "environment": {"platform": platform.platform(), "python": platform.python_version(),
                              "processor": platform.processor()},
              "stages": {"build": "first corpus read until persisted graph/index complete; no_graph is N/A",
                         "load": "process startup until query ready, recorded once per run",
                         "search": "sum of retrieval dispatch wall times, including original-source reads",
                         "answer": "sum of model request and retry wall times from all response event records",
                         "end_to_end": "question invocation start until final answer or failure; may include scheduling/waiting"},
              "methods": {}}
    for method, group in by_method.items():
        complete = [r for r in group if r["status"] == "complete"]
        report["methods"][method] = {"attempted_questions": len(group), "completed_questions": len(complete),
                                     "failed_questions": len(group) - len(complete),
                                     "retry_events": sum(r["failed_answer_attempts"] for r in group),
                                     "search": stage_summary([r["search_seconds"] for r in complete if r["search_seconds"] is not None]),
                                     "answer": stage_summary([r["answer_seconds"] for r in complete if r["answer_seconds"] is not None]),
                                     "end_to_end": stage_summary([r["end_to_end_seconds"] for r in complete if r["end_to_end_seconds"] is not None])}
    (a.output / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k: {"completed": v["completed_questions"], "attempted": v["attempted_questions"]}
                      for k, v in report["methods"].items()}, ensure_ascii=False))


if __name__ == "__main__":
    main()
