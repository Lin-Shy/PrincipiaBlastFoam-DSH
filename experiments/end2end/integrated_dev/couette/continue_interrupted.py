"""Resume a transport-interrupted DSH session with its original node result and budget."""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import zipfile

from pair import ARMS,PAIR,base,read,sha,write
from run_pair import HERE,common_environment,files,launch_attempt,runtime
from model_budget import Gate,serve,upstream


def resume(arm,pair=PAIR,exchange_name="pipe_exchange",result_name="profile.csv",result_hash="profile_sha256"):
    root = pair/arm
    first = read(root/"sealed.json")
    history = read(root/"provider_ledger/ledger.json")["events"]
    grant = read(root/"attempt_intent.json")["authorization"]
    last = history[-1]
    if first["archive_sha256"] != sha(root/"submission.zip") or first["requests"]!=len(history):
        raise ValueError("first seal or request count changed")
    if last["state"]!="unknown" or last.get("error_type") not in {"URLError","RemoteDisconnected","IncompleteRead","TimeoutError"} or len(history)>=grant["max_requests_per_arm"]:
        raise ValueError("no interrupted request within the original budget")
    outcome = read(root/"native_outcome.json")
    events = [json.loads(line) for line in (root/"native_events.jsonl").read_bytes().splitlines()]
    calls = Counter(r["event"]["data"]["callId"] for r in events if r["event"]["type"]=="tool/call")
    results = Counter(r["event"]["data"]["message"]["source"]["callId"] for r in events if r["event"]["type"]=="tool/result")
    if calls!=results or any(n!=1 for n in calls.values()) or {r["session_id"] for r in events}!={outcome["session_id"]}:
        raise ValueError("ambiguous tool or session state")
    binding = read(base/"pilot_decision_20261117"/(arm+".binding.json"))
    binding.pop("cluster",None)
    launch_attempt.check(pair,arm,binding,grant)
    creds = {}
    for line in Path(binding["credential_file"]).read_text(encoding="utf-8-sig").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k,v=line.split("=",1)
            creds[k.strip()] = v.strip().strip('"').strip("'")
    endpoint = creds["CHAPTER3_BASE_URL"].rstrip("/")
    if hashlib.sha256(endpoint.encode()).hexdigest()!=grant["endpoint_sha256"] or creds["CHAPTER3_MODEL"]!=grant["model"]:
        raise ValueError("model binding changed")
    job_id=None
    prompt_text="上一次模型请求传输中断。继续原任务，沿用原会话、工作区和请求预算。"
    if exchange_name:
        source=root/"operator/post_seal_return"
        if not source.exists():
            source=root/"workspace"/exchange_name
        receipt=read(root/"operator/verified.json")
        if read(source/"receipt.json")!=receipt or sha(source/result_name)!=receipt[result_hash]:
            raise ValueError("node collection not verified")
        for n in ("receipt.json",result_name):
            target=root/"workspace"/exchange_name/n
            if target.exists() and sha(target)!=sha(source/n):
                raise ValueError("returned file conflict")
            if not target.exists():
                shutil.copyfile(source/n,target)
        job_id=receipt["job_id"]
        prompt_text+=" 本次作业已回收，沿用原 JobID。"
    dest = root/"continuation"
    lock = runtime.parent/"chapter3-model.lock"
    with lock.open("x",encoding="utf8") as stream:
        json.dump(dict(pid=os.getpid(),arm=arm,pair=str(pair)),stream)
    server = None
    try:
        dest.mkdir(exist_ok=False)
        write(dest/"intent.json",dict(session_id=outcome["session_id"],first_seal=sha(root/"sealed.json"),
              previous_events_sha256=sha(root/"native_events.jsonl"),offset=len(history),
              cap=grant["max_requests_per_arm"],job=job_id,new_jobs=0))
        gate = Gate(dest/"provider_ledger",grant["model"],grant["max_requests_per_arm"],grant["max_output_tokens"],
                    upstream(endpoint,creds["CHAPTER3_API_KEY"],180),grant["generation"])
        gate.events.extend(history)
        gate.save()
        server = serve(gate)
        overlay = read(root/"approved.patch.yml")
        overlay[0]["config"]["providers"]["chapter3-approved"]["baseURL"]=f"http://127.0.0.1:{server.server_port}/v1"
        write(dest/"overlay.json",overlay)
        prompt = dest/"continue.txt"
        prompt.write_text(prompt_text,encoding="utf8")
        env = dict(common_environment(root),C3_PYTHON=sys.executable,C3_MODULE_PATH=str(HERE.parent),C3_RUNTIME=str(runtime),C3_GATE_TOKEN=gate.token)
        command = [launch_attempt.runtime_node(runtime),str(HERE/"native_resume.mjs"),str(root),str(runtime),
                   str(dest/"overlay.json"),str(prompt),outcome["session_id"]]
        earlier = read(root/"attempt_exit.json")["wall_seconds"]
        start = time.monotonic()
        with (dest/"stdout.log").open("xb") as out,(dest/"stderr.log").open("xb") as err:
            try:
                code = subprocess.run(command,cwd=root/"workspace",env=env,stdout=out,stderr=err,timeout=max(1,grant["wall_seconds"]-earlier)).returncode
            except subprocess.TimeoutExpired:
                code = 1
        deliver = root/"workspace/delivery"
        with zipfile.ZipFile(dest/"submission.zip","x",compression=zipfile.ZIP_DEFLATED) as z:
            for file in sorted(deliver.rglob("*")):
                if file.is_symlink() or getattr(file.lstat(),"st_file_attributes",0)&1024:
                    raise ValueError("linked output")
                if file.is_file():
                    z.write(file,file.relative_to(deliver))
        write(dest/"sealed.json",dict(exit=code,archive_sha256=sha(dest/"submission.zip"),files=files(deliver),
            requests=len(gate.events),tokens_reported=sum(e["usage"]["total_tokens"] for e in gate.events if e.get("usage")),
            unsettled=[e["request"] for e in gate.events if not e.get("usage")],wall_seconds=earlier+time.monotonic()-start))
    finally:
        if server:
            server.shutdown()
            server.server_close()
        if read(lock)["pid"]==os.getpid():
            lock.unlink()


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("arm",choices=ARMS)
    resume(p.parse_args().arm)
