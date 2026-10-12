"""Derive holdout quality timing across the recorded 16-worker/12-worker resume."""
import argparse
from collections import defaultdict
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
    a = p.parse_args()
    root = a.run.resolve()
    protocol = read(root / "protocol.json")
    if protocol["split"] != "holdout" or protocol["replicates"] != 3:
        raise ValueError("wrong timing run")
    journals = [(path, row) for path in sorted((root / "invocations").glob("*.json"))
                if (row := read(path)).get("command") == "run"]
    phases = [{"journal_sha256": sha(path), "started_unix_ns": row["started_unix_ns"],
               "workers": row["workers"], "completed": row["completed"],
               "errors": len(row["errors"]), "state": row["state"]} for path, row in journals]
    if not phases or any(x["workers"] not in (12, 16) for x in phases):
        raise ValueError("unrecognized holdout concurrency phases")
    rows, methods = [], {}
    for arm in ARMS:
        arm_root = root / arm
        sessions = sorted((arm_root / "sessions").glob("*"))
        if len(sessions) != 720 or any(not (session / "result.json").is_file() for session in sessions):
            raise ValueError("quality session grid incomplete: " + arm)
        group = []
        for session in sessions:
            row = record_for_session(arm_root, session, arm, "holdout", "quality", 12)
            attempts = [read(path) for path in sorted((session / "invocations").glob("*.json"))]
            active = [x for x in attempts if x.get("replay") is False]
            if not active or active[-1].get("elapsed_seconds") is None:
                raise ValueError("session has no terminal timed invocation: " + str(session))
            first_start = min(x["started_unix_ns"] for x in active)
            last_end = active[-1]["started_unix_ns"] + round(active[-1]["elapsed_seconds"] * 1e9)
            if last_end < first_start:
                raise ValueError("negative end-to-end interval")
            row["concurrency"] = "mixed_quality_16_then_12"
            row["end_to_end_seconds"] = (last_end-first_start)/1e9
            row["interrupted_or_resumed"] = len(active) > 1
            row["active_invocation_seconds"] = sum(x["elapsed_seconds"] or 0 for x in active)
            row["between_invocations_seconds"] = max(0, row["end_to_end_seconds"]-row["active_invocation_seconds"])
            group.append(row)
        rows.extend(group)
        complete = [row for row in group if row["status"] == "complete"]
        methods[arm] = {"attempted_questions": len(group), "completed_questions": len(complete),
                        "failed_questions": len(group)-len(complete),
                        "retry_events": sum(row["failed_answer_attempts"] for row in group),
                        "resumed_sessions": sum(row["interrupted_or_resumed"] for row in group),
                        "search": stage_summary([row["search_seconds"] for row in complete if row["search_seconds"] is not None]),
                        "answer": stage_summary([row["answer_seconds"] for row in complete if row["answer_seconds"] is not None]),
                        "end_to_end": stage_summary([row["end_to_end_seconds"] for row in complete])}
    report = {"schema": "chapter2-holdout-mixed-quality-timing-v1", "mode": "quality",
              "run_protocol_sha256": sha(root / "protocol.json"), "concurrency_phases": phases,
              "end_to_end": "first question invocation start to terminal invocation completion, including the API-balance interruption between resumes; not a standalone performance benchmark",
              "methods": methods}
    a.output.mkdir(parents=True, exist_ok=False)
    (a.output / "per-question.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows))
    (a.output / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({arm: x["completed_questions"] for arm, x in methods.items()}))


if __name__ == "__main__":
    main()
