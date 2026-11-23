"""Public-package-only stratified increment for the 2026-11-21 Chapter 3 release."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import threading
import time
import zipfile

SOURCE=Path(__file__).resolve().parent
sys.path.insert(0,str(SOURCE.parent/"pipe_flow"))
import run_pair
from run_pair import ARMS,WS,base,read,sha,write
import cluster_job
from accounting_status import status
from node_client import validate

DATA=WS/"graduation-datasets/chapter03_simulation_tasks/expansion_20261121"
OUT=base/"expansion_public_increment_20261121"
STRATA=("node-solve","engineering-readout","audit")


def prepare():
    ready=read(DATA/"READY.json")
    indexed={}
    selected={}
    for item in ready["tasks"]:
        path=DATA/item["archive"]
        if not path.resolve().is_relative_to((DATA/"packages").resolve()) or item["split"]!="development" or sha(path)!=item["sha256"]:
            raise ValueError("public archive binding mismatch")
        with zipfile.ZipFile(path) as z:
            if set(z.namelist())!={"task.json","settings.json","records.json"} or z.testzip() is not None:
                raise ValueError("unexpected public package")
            if json.loads(z.read("task.json"))["id"]!=item["id"]:
                raise ValueError("public task identity mismatch")
        indexed[item["id"]]=item["sha256"]
        selected.setdefault(item["stratum"],item)
    if len(indexed)!=ready["task_count"] or set(selected)!=set(STRATA):
        raise ValueError("public release dimensions changed")
    OUT.mkdir(exist_ok=False)
    write(OUT/"intake.json",dict(ready_sha256=sha(DATA/"READY.json"),packages=indexed,
          selector="first in READY order for each stratum",selected=[selected[s]["id"] for s in STRATA],
          model="deepseek-v4.1-flash",requests_per_arm=100,node_jobs_per_arm=1,node_minutes_per_arm=15))
    for stratum in STRATA:
        item=selected[stratum]
        prepare_pair(item)


def prepare_pair(item):
    stratum=item["stratum"]
    pair=OUT/item["id"]
    run_pair.PAIR=pair
    run_pair.prepare()
    manifest=read(pair/"manifest.json")
    pins=manifest["source_sha256"]
    for arm in ARMS:
        root=pair/arm
        work=root/"workspace"
        prompt="独立完成 task.json，公开输入为 settings.json 和 records.json。将题面要求的 report.json 放入 delivery/。仅使用当前公开包及本臂工具。"
        # Remove only the two copied PIPE-01 placeholders in this newly prepared workspace.
        for placeholder in (work/"TASK.md",work/"common/pipe_client.py"):
            pins.pop(str(placeholder),None)
            placeholder.unlink()
        with zipfile.ZipFile(DATA/item["archive"]) as z:
            for n in ("task.json","settings.json","records.json"):
                (work/n).write_bytes(z.read(n))
        if stratum=="node-solve":
            shutil.copyfile(SOURCE/"node_client.py",work/"common/node_client.py")
            prompt+=" 共同节点接口要求你离散内部节点方程，按行主序（先 y 后 x）在 case.json 写 nx、ny、浮点二维数组 matrix 和一维 rhs，矩阵仅含内部未知量。节点计算线性解并补零壁面，回传 node_exchange/field.json 与 receipt.json。用 python common/node_client.py submit 登记一次，用 python common/node_client.py collect 等候。禁止本地求解。"
        (root/"prompt.txt").write_text(prompt,encoding="utf8")
        pins[str(root/"prompt.txt")]=sha(root/"prompt.txt")
    for p in [SOURCE/"wave.py",SOURCE/"node_client.py",SOURCE/"duct_node.py",DATA/item["archive"],DATA/"READY.json"]:
        pins[str(p)]=sha(p)
    manifest.update(task=item["id"],stratum=stratum,public_package_sha256=item["sha256"],
                    role="stratified_public_development_increment",max_jobs=int(stratum=="node-solve"),
                    required=["report.json","public task.json criteria"])
    (pair/"manifest.json").write_text(json.dumps(manifest,indent=2,ensure_ascii=False),encoding="utf8")


def operate(pair,arm,stopped):
    root=pair/arm
    exchange=root/"workspace/node_exchange"
    while not (exchange/"request.json").is_file():
        if stopped.is_set():
            return
        time.sleep(1)
    case=read(exchange/"request.json")
    manifest=read(pair/"manifest.json")
    with zipfile.ZipFile(DATA/"packages"/(pair.name+".zip")) as z:
        validate(case,json.loads(z.read("settings.json")))
    state=root/"operator"
    rid="c3-"+pair.name.lower()+"-"+arm+"-20261121"
    cfg=read(base/"pilot_decision_20261117/acceptance.config.json")
    cfg.update(tasks=1,memory_mib=1024,wall_minutes=15)
    grant=dict(live_actions_allowed=True,actions=["stage","submit","status","collect"],run_ids=[rid],
               limits={k:cfg[k] for k in ("tasks","memory_mib","wall_minutes")})
    payload=state/"input"
    if not (state/"stage_receipt.json").exists():
        payload.mkdir(parents=True,exist_ok=False)
        write(payload/"case.json",case)
        program=SOURCE/"duct_node.py"
        if sha(program)!=manifest["source_sha256"][str(program)]:
            raise ValueError("changed node program")
        shutil.copyfile(program,payload/"duct_node.py")
        (payload/"run_case.sh").write_bytes(b"set -eu\nexec /usr/bin/python3 -I payload/duct_node.py\n")
        cluster_job.run("stage",cfg,rid,state,payload,grant)
    if not (state/"job_receipt.json").exists():
        if not (state/"submit_intent.json").exists():
            try:
                cluster_job.run("submit",cfg,rid,state,grant=grant)
            except (subprocess.SubprocessError,OSError):
                if not (state/"submit_intent.json").exists():
                    raise
        if not (state/"job_receipt.json").exists():
            rows=cluster_job.ssh(cfg,"sacct -nXP -S 2026-11-21 --name="+rid+" -o JobID,JobName%64,WorkDir%250",capture_output=True,text=True).stdout.splitlines()
            if len(rows)!=1:
                raise ValueError("submission state ambiguous")
            job,name,remote=rows[0].strip().split("|")
            if not job.isdigit() or name!=rid or remote!=cluster_job.REMOTE_ROOT+"/"+rid:
                raise ValueError("unmatched job identity")
            write(state/"job_receipt.json",dict(job_id=job,run_id=rid,remote=remote))
    receipt=read(state/"job_receipt.json")
    terminal=None
    for _ in range(240):
        try:
            fields=status(cfg,rid,receipt)
        except (subprocess.SubprocessError,OSError,ValueError):
            time.sleep(8)
            continue
        with (state/"status.jsonl").open("a",encoding="utf8") as f:
            f.write(json.dumps(fields)+"\n")
        if fields["JobState"] not in ("PENDING","CONFIGURING","RUNNING","COMPLETING"):
            terminal=fields
            break
        time.sleep(8)
    if terminal is None:
        raise TimeoutError("reconcile owned job by JobID")
    collected=cluster_job.run("collect",cfg,rid,state,grant=grant)
    if terminal["JobState"]!="COMPLETED" or terminal["ExitCode"]!="0:0":
        write(exchange/"failure.json",terminal)
        return
    with tarfile.open(state/"collected.tar") as z:
        def member(n):
            obj=z.getmember("./"+n)
            if not obj.isfile() or obj.size>262144:
                raise ValueError("unexpected result member")
            return z.extractfile(obj).read()
        if member("logs/allocated_job_id.txt").decode().strip()!=receipt["job_id"] or member("logs/pipeline.exit").strip()!=b"0":
            raise ValueError("unverified node exit")
        raw=member("field.json")
        field=json.loads(raw)
        digest=hashlib.sha256(json.dumps(field,separators=(",",":"),allow_nan=False).encode()).hexdigest()
        result=dict(job_id=receipt["job_id"],package_sha256=manifest["public_package_sha256"],
                    field_sha256=digest,archive_sha256=collected["archive_sha256"],host=member("logs/allocated_host.txt").decode().strip(),
                    scheduler=terminal["JobState"],elapsed=terminal["RunTime"])
    write(state/"verified.json",result)
    (exchange/"field.json").write_bytes(raw)
    write(exchange/"receipt.json",result)


def run(task,arm):
    pair=OUT/task
    root=pair/arm
    if (root/"sealed.json").exists():
        if sha(root/"submission.zip")!=read(root/"sealed.json")["archive_sha256"]:
            raise ValueError("sealed ZIP changed")
        return
    run_pair.PAIR=pair
    stopped=threading.Event()
    with ThreadPoolExecutor(max_workers=1) as pool:
        worker=pool.submit(operate,pair,arm,stopped) if read(pair/"manifest.json")["max_jobs"] else None
        try:
            run_pair.run(arm)
        finally:
            stopped.set()
        if worker:
            worker.result()


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("action",choices=("prepare","run"))
    args=p.parse_args()
    if args.action=="prepare":
        prepare()
    else:
        for i,task in enumerate(read(OUT/"intake.json")["selected"]):
            for arm in (ARMS if i%2==0 else reversed(ARMS)):
                run(task,arm)
                print(task,arm,"sealed",flush=True)
