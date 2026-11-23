"""Cross-check the full release index against sealed ZIPs, ledgers and actual job receipts."""
import argparse
import hashlib
import json
import tarfile
import zipfile

from wave import ARMS,DATA,OUT,read,sha


def audit(require_complete):
    index=read(OUT/"index.json")
    ready=read(DATA/"READY.json")
    if index["ready_sha256"]!=sha(DATA/"READY.json") or len(index["tasks"])!=ready["task_count"]:
        raise ValueError("index and release identity differ")
    jobs=set()
    table={arm:dict(first=0,final=0,requests=0,tokens=0,unknown=0) for arm in ARMS}
    sealed=0
    segments=0
    for row,public in zip(index["tasks"],ready["tasks"]):
        task=row["task"]
        if task!=public["id"] or sha(DATA/public["archive"])!=row["public_sha256"]:
            raise ValueError(f"public archive mismatch: {task}")
        for arm in ARMS:
            result=row["arms"][arm]
            if not result.get("segments"):
                if require_complete:
                    raise ValueError(f"unsealed arm: {task}/{arm}")
                continue
            sealed+=1
            previous=[]
            for record in result["segments"]:
                segments+=1
                seal=read(OUT/record["seal"])
                archive=OUT/record["submission"]
                score=read(OUT/record["score"])
                if sha(archive)!=seal["archive_sha256"] or score["submission_sha256"]!=seal["archive_sha256"]:
                    raise ValueError(f"seal mismatch: {archive}")
                with zipfile.ZipFile(archive) as z:
                    if set(z.namelist())!=set(seal["files"]) or z.testzip():
                        raise ValueError(f"ZIP content mismatch: {archive}")
                events=read(archive.parent/"provider_ledger/ledger.json")["events"]
                if previous and previous!=events[:len(previous)]:
                    raise ValueError("continuation did not inherit identical request history")
                if [e["request"] for e in events]!=list(range(1,len(events)+1)) or len(events)!=seal["requests"] or len(events)>100:
                    raise ValueError("request history mismatch")
                tokens=sum(e["usage"]["total_tokens"] for e in events if e.get("usage"))
                unknown=[e["request"] for e in events if not e.get("usage")]
                if tokens!=seal["tokens_reported"] or unknown!=seal["unsettled"]:
                    raise ValueError("usage mismatch")
                previous=events
            totals=table[arm]
            totals["first"]+=int(result["segments"][0]["passed"])
            totals["final"]+=int(result["segments"][-1]["passed"])
            totals["requests"]+=len(previous)
            totals["tokens"]+=tokens
            totals["unknown"]+=len(unknown)
            if "node" in result:
                root=OUT/task/arm/"operator"
                node=read(root/"verified.json")
                job=node["job_id"]
                submit=read(root/"job_receipt.json")
                if job in jobs or job!=submit["job_id"] or node["package_sha256"]!=public["sha256"]:
                    raise ValueError("job identity mismatch")
                if sha(root/"collected.tar")!=node["archive_sha256"]:
                    raise ValueError("collected tar changed")
                scheduler=json.loads((root/"status.jsonl").read_bytes().splitlines()[-1])
                if (scheduler["JobId"],scheduler["JobState"],scheduler["ExitCode"])!=(job,"COMPLETED","0:0"):
                    raise ValueError("scheduler terminal receipt mismatch")
                with tarfile.open(root/"collected.tar") as archive:
                    if archive.extractfile("./logs/allocated_job_id.txt").read().strip()!=job.encode() or archive.extractfile("./logs/pipeline.exit").read().strip()!=b"0":
                        raise ValueError("wrong allocation or pipeline exit")
                    field=json.load(archive.extractfile("./field.json"))
                    native=hashlib.sha256(json.dumps(field,separators=(",",":"),allow_nan=False).encode()).hexdigest()
                    if native!=node["field_sha256"]:
                        raise ValueError("native field differs from operator receipt")
                jobs.add(job)
    for arm,t in table.items():
        s=index["cumulative"][arm]
        if [t[k] for k in ("first","final","requests","tokens","unknown")]!=[s[k] for k in ("first_passed","passed","requests","tokens_reported","unknown_usage")]:
            raise ValueError("index totals differ from original receipts")
    return dict(ready_sha256=index["ready_sha256"],public_packages=len(index["tasks"]),sealed_arms=sealed,
                sealed_segments=segments,verified_unique_jobs=sorted(jobs),totals=table)


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--complete",action="store_true")
    args=p.parse_args()
    print(json.dumps(audit(args.complete),indent=2))
