"""对已发生图查询做跨进程/哈希种子实验；零模型调用，不改上游算法。"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def worker(run):
    sys.path.insert(0, str(run))
    from graphify_query_backend import Backend, bounded_payload, original_paths
    import navigation_qa as qa
    qa.verify(run)
    rows = []
    for group in ("native", "text_adapter"):
        root = run/group
        backend = Backend(root/"graphify-out/graph.json")
        inverse = qa.read(root/"path-map.json")
        for path in sorted((root/"sessions").glob("*/result.json")):
            data = qa.read(path)
            used = 0
            for event in data["events"]:
                if "result" not in event:
                    continue
                audit = event["accounting"].get("native_query_audit")
                if audit:
                    raw, cost = backend.query(audit["query"], audit["token_budget"])
                    cap = min(6000,24000-used)
                    payload = bounded_payload(original_paths(raw,inverse),cap,qa.wire)
                    rows.append({"id": group+"/"+path.parent.name+"/"+str(event["step"]),
                        "raw_sha256": qa.digest(raw), "raw_sorted_lines_sha256": qa.digest("\n".join(sorted(raw.splitlines()))),
                        "payload_sha256": qa.digest(qa.wire(payload)), "payload": payload,
                        "native_seconds": cost["seconds"]})
                used += event["returned_characters"]
    output = run/"diagnostics"/("hash-worker-"+str(time.time_ns())+".json")
    qa.write(output, {"seed":os.environ.get("PYTHONHASHSEED"), "python":sys.version,
                     "hash_probe":hash("Principia Graphify QA frozen seed"), "llm_calls":0, "rows":rows})
    print(json.dumps({"output":str(output)}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--worker", action="store_true")
    args = parser.parse_args()
    if args.worker:
        worker(args.run)
        return
    def execute(seed):
        start = time.monotonic()
        process = subprocess.run([sys.executable,str(Path(__file__).resolve()),"--run",str(args.run),"--worker"],
            env={**os.environ,"PYTHONHASHSEED":seed},capture_output=True,text=True,timeout=60,check=True)
        path = Path(json.loads(process.stdout.strip())["output"])
        return {"path":str(path),"elapsed_seconds":time.monotonic()-start,
                "sha256":hashlib.sha256(path.read_bytes()).hexdigest(), "result":json.loads(path.read_text())}
    with ThreadPoolExecutor(max_workers=3) as pool:
        runs = list(pool.map(execute,["0","0","0","1"]))
    index = [{r["id"]:r for r in x["result"]["rows"]} for x in runs]
    if any(set(x) != set(index[0]) for x in index):
        raise ValueError("Query identities differ")
    checks = [{"id":qid,
        "seed0_three_processes_identical":len({index[n][qid]["payload_sha256"] for n in range(3)}) == 1,
        "seed_changes_raw_order":index[0][qid]["raw_sha256"] != index[3][qid]["raw_sha256"],
        "seed_preserves_native_line_multiset":index[0][qid]["raw_sorted_lines_sha256"] == index[3][qid]["raw_sorted_lines_sha256"],
        "seed_changes_capped_payload":index[0][qid]["payload_sha256"] != index[3][qid]["payload_sha256"],
        "seed_changes_capped_line_multiset":sorted(index[0][qid]["payload"]["graph_navigation"].splitlines()) != sorted(index[3][qid]["payload"]["graph_navigation"].splitlines())}
        for qid in sorted(index[0])]
    output = args.run/"diagnostics"/("cross-process-seed-check-"+str(time.time_ns())+".json")
    record = {"llm_calls":0,"status":"PASS" if all(x["seed0_three_processes_identical"] for x in checks) else "FAIL",
        "driver_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "runs":[{k:v for k,v in r.items() if k!="result"} for r in runs],"checks":checks,
        "counts":{key:sum(x[key] for x in checks) for key in checks[0] if key!="id"} if checks else {}}
    output.write_text(json.dumps(record,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({"output":str(output),"status":record["status"],"queries":len(checks),"counts":record["counts"]}))
    if record["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
