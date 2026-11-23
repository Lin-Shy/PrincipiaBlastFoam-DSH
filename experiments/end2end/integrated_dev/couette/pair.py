"""Independent wall-driven modification pair on the existing numeric node service."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time

SOURCE = Path(__file__).resolve().parent
PIPE = SOURCE.parent/"pipe_flow"
sys.path.insert(0,str(PIPE))
import run_pair
from run_pair import ARMS,base,read,sha,write
from operate import operate
from reconcile import recover

PAIR = base/"couette_modify_20261121"


def prepare():
    run_pair.PAIR = PAIR
    run_pair.prepare()
    path = PAIR/"manifest.json"
    manifest = read(path)
    pins = manifest["source_sha256"]
    for arm in ARMS:
        public = PAIR/arm/"workspace"
        for src,dest in [(SOURCE/"TASK.md",public/"TASK.md"),(SOURCE/"initial_case.py",public/"initial_case.py"),
            (PIPE/"pipe_client.py",public/"common/pipe_schema.py"),
            (SOURCE.parent/"pipe_flow_v2/pipe_client.py",public/"common/pipe_client.py")]:
            shutil.copyfile(src,dest)
            pins[str(src)] = sha(src)
            if dest.name!="initial_case.py":
                pins[str(dest)] = sha(dest)
    for src in SOURCE.glob("*.py"):
        pins[str(src)] = sha(src)
    manifest.update(task="COUETTE-A01",role="independent_development_modification_pair",
                    starting_point="same public case generator, lower wall stationary; upper +0.1 m/s",
                    targets=["modified wall conditions","allocated solve","native velocity","signed flow per width",
                             "signed shear","reproducible project"])
    path.write_text(json.dumps(manifest,indent=2,ensure_ascii=False),encoding="utf8")


def operator(arm,launch_stopped=None):
    root = PAIR/arm
    state = root/"operator"
    rid = "c3-couette-a01-"+arm+"-20261121"
    while not (root/"workspace/pipe_exchange/request.json").exists():
        if (root/"sealed.json").exists() or (launch_stopped and launch_stopped.is_set()):
            return "no request"
        time.sleep(2)
    # On an interrupted SSH response, reconcile the existing intent only.
    for attempt in range(4):
        try:
            if (state/"verified.json").exists():
                return "returned"
            if (state/"stage_intent.json").exists() and not (state/"stage_receipt.json").exists():
                from recover_stage import recover as recover_stage
                recover_stage(arm)
            if (state/"submit_intent.json").exists() and not (state/"job_receipt.json").exists():
                recover(arm,pair=PAIR,run_id=rid)
            else:
                operate(arm,pair=PAIR,run_id=rid,collect_only=(state/"job_receipt.json").exists())
            return "completed operator action"
        except (subprocess.SubprocessError,OSError,TimeoutError) as exc:
            write(root/f"operator_transport_{time.time_ns()}.json",dict(error=type(exc).__name__,attempt=attempt+1,
                  job_id_known=(state/"job_receipt.json").exists()))
            if not (state/"stage_intent.json").exists():
                raise
            time.sleep(5)
    raise RuntimeError("operator unable to reconcile the owned job")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("action",choices=("prepare","pair","operator"))
    p.add_argument("arm",nargs="?",choices=ARMS)
    args = p.parse_args()
    run_pair.PAIR = PAIR
    if args.action=="prepare":
        return prepare()
    if args.action=="operator":
        if not args.arm:
            p.error("arm required")
        return operator(args.arm)
    for arm in ARMS:
        with ThreadPoolExecutor(max_workers=1) as pool:
            stopped = threading.Event()
            worker = pool.submit(operator,arm,stopped)
            try:
                if not (PAIR/arm/"sealed.json").exists():
                    run_pair.run(arm)
            finally:
                stopped.set()
            operator_result = worker.result()
            print(arm,operator_result,flush=True)
        root = PAIR/arm
        interrupted = read(root/"provider_ledger/ledger.json")["events"]
        if (not (root/"continuation").exists() and (root/"operator/verified.json").exists()
                and interrupted and interrupted[-1].get("state")=="unknown"
                and interrupted[-1].get("error_type") in {"URLError","RemoteDisconnected","IncompleteRead","TimeoutError"}
                and len(interrupted)<read(root/"attempt_intent.json")["authorization"]["max_requests_per_arm"]):
            from continue_interrupted import resume
            resume(arm)


if __name__=="__main__":
    main()
