"""Run each published diagnostic through the revised professional profile once."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile
from measurement_replay import OUT, wave, sha, read, write
from measurement_profile import HERE, PLUGIN, extend_profile
from local_first_wave import launch_attempt, common_environment, runtime_digest, snapshot_runtime, runtime

DATA = wave.DATA.parent / "diagnostic_20261122"
TEMPLATE = wave.base / "B11_dispatch_review_20261118/live/professional"


def prepare(item, pair):
    root = pair / "professional"
    work = root / "workspace"
    subprocess.run([sys.executable,"-B",str(DATA/"pack.py"),"dispatch",item["id"],str(work)],check=True)
    for name in ["workspace/common","workspace/delivery","home","tmp","user","cache","agents_home"]:
        (root/name).mkdir()
    shutil.copytree(TEMPLATE/"skills",root/"skills")
    dump = (TEMPLATE/"dump.yml").read_text(encoding="utf8").replace(str(TEMPLATE),str(root))
    (root/"dump.yml").write_text(extend_profile(dump,root),encoding="utf8")
    (root/"prompt.txt").write_text("独立完成 task.json，公开输入为 settings.json 和 records.json。将题面要求的 report.json 放入 delivery/。仅使用当前公开包及本臂工具。",encoding="utf8")
    pins = [DATA/"READY.json",DATA/item["archive"],PLUGIN,HERE/"measurement_profile.py",Path(__file__),
            HERE/"pressure-tool.mjs",HERE.parent/"native_attempt.mjs",HERE.parent/"launch_attempt.py",
            runtime/"snapshot.json", root/"dump.yml",root/"prompt.txt",*work.glob("*.json"),*(root/"skills").rglob("SKILL.md")]
    write(pair/"manifest.json",dict(item=item,source_sha256={str(p):sha(p) for p in pins},jobs=0))


def attempt(pair):
    arm = "professional"
    root = pair/arm
    binding = read(wave.base/"pilot_decision_20261117/professional.binding.json")
    binding.pop("cluster",None)
    grant = dict(live_model_allowed=True,arms=[arm],pair_manifest_sha256=sha(pair/"manifest.json"),
                 authorization_evidence="2026-11-22 user-directed ordinary-fluid diagnostic under existing request cap",
                 isolation_accepted=True,isolation_evidence="Separate same-host development workspace and session",
                 budget_unit="requests",max_requests_per_arm=100,max_output_tokens=8192,wall_seconds=14400,
                 generation=binding["generation"],**{k:binding[k] for k in ["model","context_window","endpoint_sha256"]})
    snapshot_runtime.sha = runtime_digest
    launch_attempt.common_environment = lambda r: dict(common_environment(r),C3_PYTHON=sys.executable,
                                                        C3_MODULE_PATH=str(HERE.parent),C3_RUNTIME=str(runtime))
    code = launch_attempt.run(pair,arm,binding,grant)
    report = root/"workspace/delivery/report.json"
    archive = root/"submission.zip"
    with zipfile.ZipFile(archive,"x",compression=zipfile.ZIP_DEFLATED) as z:
        for p in sorted((root/"workspace/delivery").rglob("*")):
            if p.is_symlink() or getattr(p.lstat(),"st_file_attributes",0)&1024:
                raise ValueError("linked submission")
            if p.is_file():
                z.write(p,p.relative_to(root/"workspace/delivery"))
    events = read(root/"provider_ledger/ledger.json")["events"]
    write(root/"sealed.json",dict(exit=code,archive_sha256=sha(archive),model=binding["model"],requests=len(events),
          tokens_reported=sum(e["usage"]["total_tokens"] for e in events if e.get("usage")),
          unknown_usage=sum(not e.get("usage") for e in events),money=None,cluster_jobs=0))
    if report.is_file():
        with zipfile.ZipFile(archive) as z:
            sealed = root/"sealed-report.json"
            sealed.write_bytes(z.read("report.json"))
        grade = subprocess.run([sys.executable,"-B",str(DATA/"pack.py"),"grade",pair.name,str(sealed)],
                               capture_output=True,text=True,check=False)
        result = dict(passed=grade.returncode==0,fields=json.loads(grade.stdout),report_sha256=sha(sealed))
    else:
        result = dict(passed=False,reason="missing report")
    write(root/"grade.json",result)
    print(pair.name,result,flush=True)


if __name__ == "__main__":
    ready = read(DATA/"READY.json")
    for name,digest in ready["judge_sha256"].items():
        assert sha(DATA/name)==digest
    for item in ready["tasks"]:
        assert item["split"]=="development" and item["stratum"] in ("audit","engineering-readout")
        assert sha(DATA/item["archive"])==item["sha256"]
        pair = OUT/"live"/item["id"]
        if (pair/"professional/grade.json").exists():
            continue
        if not pair.exists():
            prepare(item,pair)
        attempt(pair)
