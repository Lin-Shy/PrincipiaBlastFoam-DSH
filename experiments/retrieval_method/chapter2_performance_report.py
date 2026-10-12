"""Summarize the five sequential runs without treating builds/loads as questions."""
import argparse
import hashlib
import json
from pathlib import Path

from chapter2_segmented_timing import record_for_session, stage_summary


ARMS = ("control", "native", "text_adapter", "principia_index_free", "vector_e5_dense")


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--construction-report", type=Path)
    a = p.parse_args()
    root = a.run.resolve()
    protocol = read(root / "protocol.json")
    if protocol["split"] != "dev" or protocol["replicates"] != 1:
        raise ValueError("not a one-repeat development performance run")
    selection_path = root / "sample-selection.json"
    sampled = selection_path.exists()
    launcher_path = root / ("sampled-performance.json" if sampled else "sequential-performance.json")
    launcher = read(launcher_path)
    load_only_path = root / "sampled-load-only.json"
    load_only = read(load_only_path) if sampled and load_only_path.exists() else None
    question_ids = launcher.get("question_ids") if sampled else None
    if sampled and (not question_ids or sha(selection_path) != launcher.get("selection_sha256")):
        raise ValueError("sample selection and launcher differ")
    if [x["arm"] for x in launcher["arms"]] != list(ARMS):
        raise ValueError("methods were not run in the fixed sequential order")
    construction = read(a.construction_report) if a.construction_report else {}
    rows, methods = [], {}
    for arm in ARMS:
        arm_root = root / arm
        sessions = ([arm_root / "sessions" / f"{qid}--{protocol['groups'][arm][0]}--r1" for qid in question_ids]
                    if sampled else sorted((arm_root / "sessions").glob("*")))
        expected = len(question_ids) if sampled else 60
        if len(sessions) != expected or any(not (session / "result.json").is_file() for session in sessions):
            raise ValueError("incomplete performance session grid: " + arm)
        group = [record_for_session(arm_root, session, arm, "dev", "sequential_performance", 1) for session in sessions]
        rows.extend(group)
        complete = [row for row in group if row["status"] == "complete"]
        if sampled:
            launcher_row = next(x for x in launcher["arms"] if x["arm"] == arm)
            if launcher_row["completed_results"] != expected or launcher_row["process_exit_code"] not in (0, None):
                raise ValueError("sampled performance invocation failed: " + arm)
            measured_load = next((x for x in load_only["arms"] if x["arm"] == arm), None) if load_only else None
            load_seconds = measured_load["process_start_to_query_ready_seconds"] if measured_load else launcher_row["process_start_to_query_ready_seconds"]
            engine_load_seconds = measured_load["engine_load_seconds"] if measured_load else launcher_row["engine_load_seconds"]
        else:
            load = read(arm_root / "load-measurement.json")
            if load["process_exit_code"] != 0 or load["completed_results"] != expected:
                raise ValueError("performance invocation failed: " + arm)
            load_seconds = load["startup_to_query_ready_seconds"]
            engine_load_seconds = load["engine_load_seconds"]
        cold = construction.get("methods", {}).get(arm)
        if arm == "control":
            build = {"not_applicable": True, **stage_summary([])}
        elif cold and cold.get("status") == "completed_cold_build":
            build = {"not_applicable": False, "source": cold["source"],
                     "source_sha256": cold["source_sha256"], **stage_summary([cold["seconds"]])}
        else:
            build = {"not_applicable": False, "reason": "no comparable cold corpus-to-persisted-artifact run recorded",
                     **stage_summary([])}
        methods[arm] = {"attempted_questions": len(group), "completed_questions": len(complete),
                        "failed_questions": len(group) - len(complete),
                        "retry_events": sum(row["failed_answer_attempts"] for row in group),
                        "build": build,
                        "load": {"endpoint": "process start to query-ready", "engine_construction_seconds": engine_load_seconds,
                                 **stage_summary([load_seconds] if load_seconds is not None else [])},
                        "search": stage_summary([row["search_seconds"] for row in complete if row["search_seconds"] is not None]),
                        "answer": stage_summary([row["answer_seconds"] for row in complete if row["answer_seconds"] is not None]),
                        "end_to_end": stage_summary([row["end_to_end_seconds"] for row in complete if row["end_to_end_seconds"] is not None])}
    result = {"schema": "chapter2-sequential-performance-summary-v1", "mode": "sequential_performance",
              "split": "dev", "concurrency": 1, "run_protocol_sha256": sha(root / "protocol.json"),
              "launcher_sha256": sha(launcher_path),
              "load_only_sha256": sha(load_only_path) if load_only else None,
              "performance_sample": {"question_ids": question_ids, "planned_per_method": len(question_ids),
                                     "selection_sha256": sha(selection_path)} if sampled else None,
              "construction_report_sha256": sha(a.construction_report) if a.construction_report else None,
              "environment": launcher.get("environment", {"concurrency": 1, "model": "deepseek-flash"}),
              "stages": {"build": "first original-corpus read to persisted graph/index; run-level",
                         "load": "process start to query ready; run-level",
                         "search": "retrieval dispatch to evidence return including original-file read; per question, summed",
                         "answer": "all model request/retry wall times; per question, summed",
                         "end_to_end": "question received to final answer or failure; per question"},
              "methods": methods}
    a.output.mkdir(parents=True, exist_ok=False)
    (a.output / "per-question.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))
    (a.output / "summary.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({arm: (row["completed_questions"], row["attempted_questions"]) for arm, row in methods.items()}))


if __name__ == "__main__":
    main()
