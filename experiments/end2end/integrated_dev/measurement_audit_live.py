"""Execute the four first attempts for the ordinary-fluid audit pair."""
from pathlib import Path
import datetime
import json
import math
import shutil
import subprocess
import sys
import zipfile
from measurement_paired_control import OUT, DIAGNOSTIC, TEMPLATE, HERE, read, write, sha, wave
from measurement_live import launch_attempt, common_environment, runtime_digest, snapshot_runtime, runtime, extend_profile

BATCH = OUT / "audit_live_50"
DATA = DIAGNOSTIC
PROTOCOL = OUT / "protocol.json"
def selected():
    ready = read(DATA/"READY.json")["tasks"]
    return [next(t["id"] for t in ready if t["family"]==family) for family in ("coverage","restart")]


coverage, restart = selected()
ORDER = [(coverage,"old"),(coverage,"revised"),(restart,"revised"),(restart,"old")]


def freeze():
    conditions=read(PROTOCOL)["same_question_conditions"]
    jobs=[(t["id"],v) for t in conditions["tasks"] if t["cohort"]==DATA.name and t["id"] in selected() for v in t["versions_in_order"]]
    assert jobs==ORDER
    for p,digest in conditions["sources"].items():
        assert sha(Path(p))==digest,p
    assert sha(OUT/"prompt.txt")==conditions["common_prompt_sha256"]
    budget=dict(version="audit-pair-12-plus-2-v1",prior_protocol_sha256=sha(PROTOCOL),
                authority="Coordinator's delegated 50-request decision, 2026-11-22",
                sessions=[dict(task=t,revision=v,max_requests=12) for t,v in ORDER],
                total_max=50,first_attempt_max=48,recovery_reserve=2,
                selection="First published READY item in each requested family, independent of grades",
                exposure="Both exact public packages were previously run by the revised system; C3X15 also occurred in the older 24-task release",
                recovery_rule="After all four first seals, consider in frozen order. Only a documented transport interruption with no report, an existing resumable session, and no outstanding request is eligible. At most one extra provider request per eligible session and two in total. Never recover for an incorrect grade, successful stop or exhaustion alone. Preserve first seal and ledger. No retries within a segment.",charge_failed_requests=True,transfer=False,retries=0,cluster_jobs=0,
                frozen_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),runner_sha256=sha(Path(__file__)))
    BATCH.mkdir(exist_ok=False)
    write(BATCH/"budget.json",budget)
    for task,revision in ORDER:
        item=next(t for t in conditions["tasks"] if t["id"]==task)
        assert sha(DATA/"READY.json")==item["ready_sha256"]
        package=DATA/"packages"/(task+".zip")
        assert sha(package)==item["package_sha256"]
        pair=BATCH/task/revision
        root=pair/"professional"
        work=root/"workspace"
        subprocess.run([sys.executable,"-B",str(DATA/"pack.py"),"dispatch",task,str(work)],check=True)
        assert {p.name:sha(p) for p in work.iterdir()}==item["files"]
        for name in ["workspace/common","workspace/delivery","home","tmp","user","cache","agents_home"]:
            (root/name).mkdir()
        shutil.copytree(TEMPLATE/"skills",root/"skills")
        dump=(TEMPLATE/"dump.yml").read_text(encoding="utf8").replace(str(TEMPLATE),str(root))
        if revision=="revised":
            dump=extend_profile(dump,root)
        (root/"dump.yml").write_text(dump,encoding="utf8")
        shutil.copyfile(OUT/"prompt.txt",root/"prompt.txt")
        pins={**conditions["sources"],**{str(p):sha(p) for p in [PROTOCOL,BATCH/"budget.json",Path(__file__),
              DATA/"READY.json",package,root/"dump.yml",root/"prompt.txt",*work.glob("*.json"),*(root/"skills").rglob("SKILL.md")]}}
        write(pair/"manifest.json",dict(item=item,revision=revision,source_sha256=pins))


def run(task,revision):
    pair=BATCH/task/revision
    root=pair/"professional"
    binding=read(wave.base/"pilot_decision_20261117/professional.binding.json")
    binding.pop("cluster",None)
    conditions=read(PROTOCOL)["same_question_conditions"]
    grant=dict(live_model_allowed=True,arms=["professional"],pair_manifest_sha256=sha(pair/"manifest.json"),
               authorization_evidence="2026-11-22 50-request decision, budget "+sha(BATCH/"budget.json"),
               isolation_accepted=True,isolation_evidence=conditions["isolation"],budget_unit="requests",
               max_requests_per_arm=12,**{k:conditions[k] for k in ("model","context_window","endpoint_sha256","generation","wall_seconds","max_output_tokens")})
    assert binding["generation"]==grant["generation"]
    snapshot_runtime.sha=runtime_digest
    launch_attempt.common_environment=lambda r: dict(common_environment(r),C3_PYTHON=sys.executable,
                                                      C3_MODULE_PATH=str(HERE.parent),C3_RUNTIME=str(runtime))
    code=launch_attempt.run(pair,"professional",binding,grant)
    archive=root/"submission.zip"
    delivery=root/"workspace/delivery"
    with zipfile.ZipFile(archive,"x",compression=zipfile.ZIP_DEFLATED) as z:
        for p in sorted(delivery.rglob("*")):
            if p.is_symlink() or getattr(p.lstat(),"st_file_attributes",0)&1024:
                raise ValueError("linked submission")
            if p.is_file():
                z.write(p,p.relative_to(delivery))
    ledger=read(root/"provider_ledger/ledger.json")
    events=ledger["events"]
    assert len(events)<=ledger["max_requests"]==12
    cost=dict(exit=code,archive_sha256=sha(archive),ledger_sha256=sha(root/"provider_ledger/ledger.json"),
              requests=len(events),tokens_reported=sum(e["usage"]["total_tokens"] for e in events if e.get("usage")),
              unknown_usage=sum(not e.get("usage") for e in events),money=None,cluster_jobs=0)
    write(root/"sealed.json",cost)
    print(task,revision,"sealed",len(events),flush=True)


if __name__=="__main__":
    freeze()
    for t,v in ORDER:
        run(t,v)
