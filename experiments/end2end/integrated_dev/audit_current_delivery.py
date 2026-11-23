"""Read-only release audit of current ordinary-fluid developer evidence."""
import hashlib
import json
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parents[4]
BASE=ROOT/"graduation-experiment-results/chapter3_end_to_end_evaluation/dsh"
def read(p):
    return json.loads(p.read_bytes())
def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    batches=[
        ("measurement_diagnostic_20261122",["live/"+t+"/professional" for t in ["C3X15","C3D01","C3D02","C3D03"]]),
        ("measurement_paired_control_20261122/annular_live_48",[t+"/"+v+"/professional" for t in ["C3X10","C3X12"] for v in ["old","revised"]]),
        ("measurement_paired_control_20261122/audit_live_50",[t+"/"+v+"/professional" for t in ["C3X15","C3D03"] for v in ["old","revised"]]),
        ("pipe_flow_paired_100_20261122",["general","professional"])]
    rows=[]
    for batch,arms in batches:
        for arm in arms:
            root=BASE/batch/arm
            seal=read(root/"sealed.json")
            assert sha(root/"submission.zip")==seal["archive_sha256"]
            ledger=read(root/"provider_ledger/ledger.json")
            events=ledger["events"]
            assert len(events)==seal["requests"]<=ledger["max_requests"]
            assert sum(e["usage"]["total_tokens"] for e in events if e.get("usage"))==seal["tokens_reported"]
            with zipfile.ZipFile(root/"submission.zip") as z:
                assert z.testzip() is None
                count=len(z.namelist())
            rows.append(dict(batch=batch,arm=arm,files=count,requests=len(events),
                             tokens_reported=seal["tokens_reported"],archive_sha256=sha(root/"submission.zip"),
                             seal_sha256=sha(root/"sealed.json"),ledger_sha256=sha(root/"provider_ledger/ledger.json")))
    print(json.dumps(dict(checked_segments=len(rows),requests=sum(r["requests"] for r in rows),
                         tokens_reported=sum(r["tokens_reported"] for r in rows),rows=rows,
                         new_model_requests=0,new_cluster_jobs=0),indent=2))

if __name__=="__main__":
    main()
