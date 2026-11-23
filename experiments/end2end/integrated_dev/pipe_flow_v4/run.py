"""Freeze offline PIPE-01 diagnostics and run the two authorized native arms."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import shutil
import sys
import time
import zipfile

HERE=Path(__file__).resolve().parent
DEV=HERE.parent
sys.path[:0]=[str(DEV/"pipe_flow"),str(DEV/"pipe_flow_v2"),str(DEV/"pipe_flow_v3")]
from run_pair import ARMS,base,read,sha,write,files
import run_pair
import round2
from operate import operate
from admission import await_input
from pipe_client import validate
from row_consistency import inspect_rows
from measurement_profile import extend_profile
from local_first_wave import launch_attempt,common_environment,runtime_digest,snapshot_runtime,runtime

PAIR=base/"pipe_flow_paired_100_20261122"
PROMPT="""从空工程完成 TASK.md。轴向正向取沿公开压力下降的方向。自己写离散化生成器、后处理和 README，提交你生成的 case.json。只用公共客户端 submit/collect，collect 等待本次节点原件。可在等待期间完成说明和后处理源码。将所有题面交件放入 delivery，并检查 README 中的命令可以从交件再生输入、由原生速度表重建摘要。在预算内交付。"""


def physics(rows,driving_sign=1):
    inspect_rows(rows,.001,.8)


def offline():
    from pipe_preflight import check_direction
    history=[]
    for batch in ["pipe_flow_20261120","pipe_flow_round2_20261120","pipe_flow_admission_20261120"]:
        for arm in ARMS:
            root=base/batch/arm
            if not (root/"sealed.json").is_file():
                continue
            archive=root/"submission.zip"
            assert sha(archive)==read(root/"sealed.json")["archive_sha256"]
            with zipfile.ZipFile(archive) as z:
                rows=json.loads(z.read("case.json").decode("utf-8-sig"))["rows"]
            checks={}
            for name,test in [("original",rows),("sign_flipped_only",[r[:-1]+[-r[-1]] for r in rows])]:
                try:
                    physics(test)
                except ValueError as exc:
                    checks[name]=str(exc)
                else:
                    checks[name]="accepted"
            history.append(dict(batch=batch,arm=arm,requests=len(read(root/"provider_ledger/ledger.json")["events"]),
                                archive_sha256=sha(archive),checks=checks))
    latest=history[-1]["checks"]
    assert "orientation" in latest["original"] and "signed pressure drop" in latest["sign_flipped_only"]
    # Synthetic row-invariance test with no velocity field or node solve.
    rows=[[float(i),-(1-.5/i) if i else 0,2.,-(1+.5/i) if i else -2.,1.] for i in range(6)]
    for factor in [1.,-3.]:
        inspect_rows([[r,*[v*factor for v in coeff]] for r,*coeff in rows],1.,1.)
    return history


def prepare():
    history=offline()
    round2.PAIR=PAIR
    round2.prepare()
    pins=read(PAIR/"manifest.json")["source_sha256"]
    for arm in ARMS:
        root=PAIR/arm
        if arm=="professional":
            common=root/"workspace/common"
            client=(DEV/"pipe_flow_v3/pipe_client.py").read_text(encoding="utf8").replace(
                "from pipe_preflight import check_direction","from row_consistency import inspect_rows").replace(
                'check_direction(case["rows"],driving_sign=1)','inspect_rows(case["rows"],.001,.8)')
            (common/"pipe_client.py").write_text(client,encoding="utf8")
            shutil.copyfile(HERE/"row_consistency.py",common/"row_consistency.py")
            skill=root/"skills/steady-pipe-delivery/SKILL.md"
            with skill.open("a",encoding="utf8") as out:
                out.write("\nUse the immutable public pressure-drop direction. If submit rejects a row, change the generator and rerun it before resubmitting; repeated tests on identical bytes cannot change the result. Check the row applied to constant and quadratic coordinates against the stated continuum operator. Keep the same geometric scaling on the integrated source and flux. The checks never supply a velocity field.\n")
            dump=root/"dump.yml"
            dump.write_text(extend_profile(dump.read_text(encoding="utf8"),root),encoding="utf8")
        (root/"prompt.txt").write_text(PROMPT,encoding="utf8")
        for p in [root/"dump.yml",root/"prompt.txt",*(root/"workspace").rglob("*.py"),*(root/"skills").rglob("SKILL.md")]:
            pins[str(p)]=sha(p)
    from measurement_profile import PLUGIN
    for p in [HERE/"row_consistency.py",Path(__file__),DEV/"pipe_flow_v3/admission.py",PLUGIN]:
        pins[str(p)]=sha(p)
    write(PAIR/"offline.json",history)
    write(PAIR/"protocol.json",dict(task="PIPE-01",task_sha256=sha(run_pair.SOURCE/"TASK.md"),from_scratch=True,
          per_arm=50,total=100,retries=0,jobs_per_arm=1,node_minutes_per_arm=15,arms=list(ARMS),budget_basis=history,
          scoring="Full signed field and signed flow thresholds from TASK.md; require real node provenance, original artifacts and clean README reproduction of matrix and postprocessing. No repair of sealed work.",
          shared="same public task, prompt, runtime, model, concurrency 1, cluster solver and physical parameters",
          arms_differ="Native DSH vs professional domain skills, tools and trusted admission. No prior project files or reference fields supplied."))
    pins[str(PAIR/"protocol.json")]=sha(PAIR/"protocol.json")
    manifest=read(PAIR/"manifest.json")
    manifest.update(max_requests=50,source_sha256=pins,role="independent_exposed_from_scratch_pipe_pair")
    (PAIR/"manifest.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf8")


def agent(arm):
    root=PAIR/arm
    binding=read(base/"pilot_decision_20261117"/(arm+".binding.json"))
    binding.pop("cluster",None)
    grant=dict(live_model_allowed=True,arms=[arm],pair_manifest_sha256=sha(PAIR/"manifest.json"),
        authorization_evidence="Delegated PIPE-01 independent batch 100, 50 requests per arm",
        isolation_accepted=True,isolation_evidence="separate same-host development workspaces",budget_unit="requests",
        max_requests_per_arm=50,max_output_tokens=8192,wall_seconds=14400,
        **{k:binding[k] for k in ("model","context_window","endpoint_sha256","generation")})
    snapshot_runtime.sha=runtime_digest
    launch_attempt.common_environment=lambda r:dict(common_environment(r),C3_PYTHON=sys.executable,C3_MODULE_PATH=str(DEV.parent),C3_RUNTIME=str(runtime))
    code=launch_attempt.run(PAIR,arm,binding,grant)
    delivery=root/"workspace/delivery"
    with zipfile.ZipFile(root/"submission.zip","x",compression=zipfile.ZIP_DEFLATED) as z:
        for p in sorted(delivery.rglob("*")):
            if p.is_symlink() or getattr(p.lstat(),"st_file_attributes",0)&1024:
                raise ValueError("linked submission")
            if p.is_file():
                z.write(p,p.relative_to(delivery))
    events=read(root/"provider_ledger/ledger.json")["events"]
    assert len(events)<=50
    write(root/"sealed.json",dict(exit=code,archive_sha256=sha(root/"submission.zip"),files=files(delivery),requests=len(events),
          tokens_reported=sum(e["usage"]["total_tokens"] for e in events if e.get("usage")),
          unknown_usage=sum(not e.get("usage") for e in events),money=None))


def operator(arm):
    root=PAIR/arm
    request=root/"workspace/pipe_exchange/request.json"
    while not request.is_file():
        if (root/"sealed.json").is_file():
            return
        time.sleep(1)
    case=await_input(root,validate,physics,write) if arm=="professional" else read(request)
    if case is not None:
        operate(arm,pair=PAIR,run_id="c3-pipe04-"+arm+"-20261122",accepted_case=case)


if __name__=="__main__":
    if sys.argv[1]=="prepare":
        prepare()
    elif sys.argv[1]=="agent":
        agent(sys.argv[2])
    elif sys.argv[1]=="operator":
        operator(sys.argv[2])
