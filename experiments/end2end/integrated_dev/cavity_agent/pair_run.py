"""Single professional-agent modification task on the verified ordinary-fluid cavity."""
from pathlib import Path
import sys,json,shutil,time,tarfile,zipfile,re
SRC=Path(__file__).resolve().parent
sys.path.insert(0,str(SRC.parent))
from measurement_live import TEMPLATE,extend_profile,launch_attempt,common_environment,runtime_digest,snapshot_runtime,runtime
from measurement_replay import wave,read,sha,write
import cluster_job
from pipe_flow.accounting_status import status
BASE=wave.base
ARM=sys.argv[2]
STUDY=BASE/"openfoam_cavity_pair100_20261122"
PAIR=STUDY/ARM
ROOT=PAIR/ARM
TEMPLATE=BASE/"B11_dispatch_review_20261118/live"/ARM
REFERENCE=BASE/"openfoam_cavity_solve_20261122_r2"
RID="c3-cavity-pair100-"+ARM+"-20261122"
FILES=("0/U","0/p","constant/transportProperties","system/blockMeshDict","system/controlDict","system/fvSchemes","system/fvSolution","system/setFieldsDict")
TASK="""# 普通流体方腔修改与交付

起始工程 case/ 为已验证的 0.1×0.1×0.01 m 顶盖驱动方腔，400单元，顶盖速度1 m/s，运动黏度0.01 m²/s。完成以下修改并在节点真实求解：
- 网格改为12×12×1（144单元），保留原几何及empty前后边界。
- 顶盖速度改为(0.25 0 0) m/s，固定壁面仍为零速度。
- 从时间0及内部静止速度、零压力开始，步长0.0025秒，推进到0.05秒，每10步写出，ASCII输出。
- 其余物性、压力参考和求解器保持与起始工程一致。
用 python common/client.py submit 登记一次，python common/client.py collect 等候。公共接口只运行 blockMesh、checkMesh、setFields、icoFoam。只提交八份普通字典，不运行自定义代码。禁止本地求解。求解输入固定后不可重新提交。
回收文件放在 exchange/。自行在 delivery/ 提交 case/ 的八份输入、原生结果 native/（完整回收的case与logs）、receipt.json、独立后处理 postprocess.py、其输出 summary.json 和 README.md。
summary应从回收原生场计算cells、final_time、max_speed_m_s以及mean_pressure_m2_s2。README说明修改、物理条件、运行步骤及从原生场重建摘要的命令。数值验证目标是完成时间推进、有限场、144单元及边界条件，未提供参考精度解。
"""
def prepare():
 PAIR.mkdir(exist_ok=False)
 for d in ["workspace/common","workspace/delivery","home","tmp","user","cache","agents_home"]:(ROOT/d).mkdir(parents=True)
 shutil.copytree(TEMPLATE/"skills",ROOT/"skills")
 shutil.copytree(REFERENCE/"payload/case",ROOT/"workspace/case")
 shutil.copyfile(SRC/"client.py",ROOT/"workspace/common/client.py")
 (ROOT/"workspace/TASK.md").write_text(TASK,encoding="utf8")
 (ROOT/"prompt.txt").write_text("完成 TASK.md，在当前工作区自主修改、登记、回收和交付。",encoding="utf8")
 config=(TEMPLATE/"dump.yml").read_text(encoding="utf8").replace(str(TEMPLATE),str(ROOT))
 (ROOT/"dump.yml").write_text(extend_profile(config,ROOT) if ARM=="professional" else config,encoding="utf8")
 write(PAIR/"protocol.json",dict(task="new public cavity modification variant",arm=ARM,total_batch_requests=100,budget_reason="previous professional complete delivery used 45 requests; 25 per arm would truncate that trajectory",max_requests=50,retries=0,jobs=1,node_minutes=5,
    source_plan_sha256=sha(REFERENCE/"plan.json"),selection="first existing verified incompressible ordinary-fluid case",
    exposure="public baseline case supplied, new parameter variant after exposed family development; source operator verification disclosed",solver_sha256=read(REFERENCE/"verified.json")["solver_sha256"],
    acceptance="Task conditions, genuine node provenance, complete delivery, independently re-run postprocessing; no reference accuracy claim",
    design_sha256=sha(wave.WS/"graduation-thesis-materials/graduation-research/chapters/chapter03.md")))
 pins=[SRC/"pair_run.py",SRC/"client.py",STUDY/"protocol.json",PAIR/"protocol.json",ROOT/"dump.yml",ROOT/"prompt.txt",
       *[p for p in (ROOT/"workspace").rglob("*") if p.is_file()],*(ROOT/"skills").rglob("SKILL.md"),
       REFERENCE/"payload/run_case.sh",SRC.parent.parent/"launch_attempt.py",SRC.parent.parent/"native_attempt.mjs"]
 write(PAIR/"manifest.json",dict(source_sha256={str(p):sha(p) for p in pins}))
def agent():
 binding=read(BASE/"pilot_decision_20261117"/(ARM+".binding.json"));binding.pop("cluster",None)
 grant=dict(live_model_allowed=True,arms=[ARM],pair_manifest_sha256=sha(PAIR/"manifest.json"),
    authorization_evidence="Delegated autonomous OpenFOAM engineering validation, paired 100-request batch, 50 per arm, no transfer",
    isolation_accepted=True,isolation_evidence="same-host public development inputs; descriptive capability only",
    budget_unit="requests",max_requests_per_arm=50,max_output_tokens=8192,wall_seconds=14400,
    **{k:binding[k] for k in ("model","context_window","generation","endpoint_sha256")})
 snapshot_runtime.sha=runtime_digest
 launch_attempt.common_environment=lambda r:dict(common_environment(r),C3_PYTHON=sys.executable,C3_MODULE_PATH=str(SRC.parent.parent),C3_RUNTIME=str(runtime))
 code=launch_attempt.run(PAIR,ARM,binding,grant)
 with zipfile.ZipFile(ROOT/"submission.zip","x",zipfile.ZIP_DEFLATED) as z:
  for p in (ROOT/"workspace/delivery").rglob("*"):
   if p.is_symlink() or getattr(p.lstat(),"st_file_attributes",0)&1024:raise ValueError("linked delivery")
   if p.is_file():z.write(p,p.relative_to(ROOT/"workspace/delivery"))
 events=read(ROOT/"provider_ledger/ledger.json")["events"]
 write(ROOT/"sealed.json",dict(exit=code,requests=len(events),tokens_reported=sum(e["usage"]["total_tokens"] for e in events if e.get("usage")),unknown_usage=sum(not e.get("usage") for e in events),archive_sha256=sha(ROOT/"submission.zip"),money=None))
def operator():
 ex=ROOT/"workspace/exchange"
 while not (ex/"request.json").exists():
  if (ROOT/"sealed.json").exists():return
  time.sleep(1)
 request=read(ex/"request.json")
 if set(request)!=set(FILES):raise ValueError("unexpected files")
 for content in request.values():
  clean=re.sub(r'/\*.*?\*/|//[^\n]*','',content,flags=re.S)
  if len(content)>100000 or re.search(r'#|\b(?:libs|functions|codeStream|systemCall)\b',clean):raise ValueError("nonliteral dictionary")
 payload=PAIR/"payload"
 for n,content in request.items():
  p=payload/"case"/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(content,encoding="utf8")
 shutil.copyfile(REFERENCE/"payload/run_case.sh",payload/"run_case.sh")
 cfg=read(BASE/"pilot_decision_20261117/acceptance.config.json");cfg.update(tasks=1,memory_mib=1024,wall_minutes=5)
 grant=dict(live_actions_allowed=True,actions=["stage","submit","status","collect"],run_ids=[RID],limits={k:cfg[k] for k in ("tasks","memory_mib","wall_minutes")})
 state=PAIR/"operator"
 cluster_job.run("stage",cfg,RID,state,payload,grant)
 receipt=cluster_job.run("submit",cfg,RID,state,grant=grant);print(receipt["job_id"],flush=True)
 for _ in range(150):
  term=status(cfg,RID,receipt)
  if term["JobState"] not in ("PENDING","RUNNING","CONFIGURING","COMPLETING"):break
  time.sleep(4)
 else:raise TimeoutError("owned job in progress")
 write(PAIR/"terminal.json",term)
 collected=cluster_job.run("collect",cfg,RID,state,grant=grant)
 if (ROOT/"sealed.json").exists():ex=PAIR/"post_seal";ex.mkdir()
 with tarfile.open(state/"collected.tar") as z:
  hashes={}
  for member in z.getmembers():
   name=member.name.removeprefix("./")
   if member.isfile() and (name.startswith("case/") or name.startswith("logs/")):
    target=(ex/"native"/name).resolve()
    if not target.is_relative_to((ex/"native").resolve()) or member.size>5000000:raise ValueError("invalid member")
    target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(z.extractfile(member).read());hashes[name]=sha(target)
 record=dict(job_id=receipt["job_id"],scheduler=term["JobState"],exit_code=term["ExitCode"],input_sha256=sha(ex/"request.json"),archive_sha256=collected["archive_sha256"],files=hashes)
 write(ex/"receipt.json",record)
if __name__=="__main__":
 {"prepare":prepare,"agent":agent,"operator":operator}[sys.argv[1]]()
