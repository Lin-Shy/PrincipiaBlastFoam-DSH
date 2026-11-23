"""Finish the existing v1.0.0 release in READY order, one variant at a time."""
from concurrent.futures import ThreadPoolExecutor
import json
import sys
import threading
import time

from wave import ARMS,DATA,OUT,SOURCE,operate,prepare_pair,read,run,sha,write

sys.path.insert(0,str(SOURCE.parent/"couette"))
from continue_interrupted import resume


def continuation(pair,arm):
    root=pair/arm
    first=read(root/"sealed.json")
    if (root/"continuation/sealed.json").exists() or not first["unsettled"] or first["requests"]>=100:
        return
    last=read(root/"provider_ledger/ledger.json")["events"][-1]
    if last["state"]!="unknown" or last.get("error_type") not in {"URLError","IncompleteRead","RemoteDisconnected","TimeoutError"}:
        return
    if not read(pair/"manifest.json")["max_jobs"]:
        resume(arm,pair,exchange_name=None)
    elif (root/"operator/verified.json").exists():
        resume(arm,pair,"node_exchange","field.json","field_sha256")
    else:
        stopped=threading.Event()
        with ThreadPoolExecutor(max_workers=1) as pool:
            operator=pool.submit(operate,pair,arm,stopped)
            try:
                resume(arm,pair,exchange_name=None)
            finally:
                stopped.set()
            operator.result()


def main():
    ready=read(DATA/"READY.json")
    original=read(OUT/"intake.json")
    if ready["version"]!="1.0.0" or sha(DATA/"READY.json")!=original["ready_sha256"]:
        raise ValueError("release changed")
    plan=OUT/"remaining_variants.json"
    batches=[[t["id"] for t in ready["tasks"] if t["variant"]==i] for i in (2,3,4)]
    policy=dict(ready_sha256=original["ready_sha256"],batches=batches,requests_per_arm=100,
                node_job_limit_per_arm=1,node_minutes_per_job=15,continuations="one per eligible transport interruption; cumulative cap")
    if not plan.exists():
        write(plan,policy)
    if read(plan)!=policy:
        raise ValueError("queue plan changed")
    items={t["id"]:t for t in ready["tasks"]}
    for batch in batches:
        for i,task in enumerate(batch):
            item=items[task]
            if sha(DATA/item["archive"])!=original["packages"][task]:
                raise ValueError("public package changed")
            pair=OUT/task
            if not pair.exists():
                prepare_pair(item)
            for arm in (ARMS if (i+item["variant"])%2==0 else reversed(ARMS)):
                try:
                    run(task,arm)
                    continuation(pair,arm)
                    print(task,arm,"sealed",flush=True)
                except Exception as exc:
                    write(OUT/f"incident-{task}-{arm}-{time.time_ns()}.json",dict(task=task,arm=arm,
                          exception=type(exc).__name__,detail=str(exc)))
                    print(task,arm,"incident",type(exc).__name__,flush=True)


if __name__=="__main__":
    main()
