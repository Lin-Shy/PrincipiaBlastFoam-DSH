"""Read-only reconciliation of effective Chapter 3 records and sealed archives."""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import zipfile


def audit(batch):
    states = json.loads((batch/"task_states.json").read_bytes())
    rows = []
    totals = defaultdict(lambda: dict(issued=0, started=0, complete=0, requests=0,
                                      reported_tokens=0, cluster_jobs=0, unsettled_requests=0))
    for task, state in states.items():
        for arm, result in state["actual"].items():
            card = json.loads((batch/result["scorecard"]).read_bytes())
            costs = json.loads((batch/result["cost"]).read_bytes())
            if card["task_id"] != task or card["system"] != arm:
                raise ValueError(f"score identity mismatch: {task}/{arm}")
            digest = None
            if result["submission"]:
                path = batch/result["submission"]
                digest = hashlib.sha256(path.read_bytes()).hexdigest()
                receipt = json.loads((batch/result["run_evidence"]).read_bytes())
                if digest != receipt.get("archive_sha256",receipt.get("submission_sha256")):
                    raise ValueError(f"archive digest mismatch: {task}/{arm}")
                with zipfile.ZipFile(path) as archive:
                    if archive.testzip() is not None:
                        raise ValueError(f"damaged ZIP: {task}/{arm}")
            group = totals[state["scope"]+"/"+arm]
            group["issued"] += 1
            group["started"] += int(bool(result["run_evidence"]))
            group["complete"] += int(result["achieved"] == "完整交付")
            for key in ("requests","reported_tokens","cluster_jobs"):
                group[key] += result[key] or 0
            group["unsettled_requests"] += len(costs.get("unsettled") or [])
            rows.append(dict(task=task, scope=state["scope"], arm=arm, **result,
                             archive_sha256=digest, cost_record=costs, money=costs.get("actual_money")))
    return dict(scope="effective development attempts only; selected replacements included",
                task_states_sha256=hashlib.sha256((batch/"task_states.json").read_bytes()).hexdigest(),
                totals=dict(totals), rows=rows)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("batch",type=Path)
    p.add_argument("output",type=Path)
    args = p.parse_args()
    report = audit(args.batch)
    with args.output.open("x",encoding="utf8") as output:
        json.dump(report,output,indent=2,ensure_ascii=False)
