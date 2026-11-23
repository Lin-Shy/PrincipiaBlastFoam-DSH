"""Prepare two isolated chapter profiles and a public S10 development task.

No model/SSH/cluster action. --dump-config only loads local config, no agent run.
Shared DSH binaries remain hash-pinned external dependencies, not an OS sandbox.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys

HERE=Path(__file__).resolve().parent
WS=next(parent for parent in HERE.parents if (parent/'PrincipiaBlastFoam-DSH/AGENTS.md').is_file())
PROJECT=WS/'PrincipiaBlastFoam-DSH'
sys.path.insert(0,str(HERE))
from engineering_delivery import public_brief, operator_records
ARCHIVE=WS/'graduation-experiment-results/chapter3_end_to_end_evaluation/dsh'

def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
    return h.hexdigest()
def write(p,data):
    p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('x',encoding='utf-8') as f:json.dump(data,f,ensure_ascii=False,indent=2)
def copy(src,dst,pins):
    if src.is_symlink():raise ValueError('symlink source refused')
    before=sha(src);dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,dst)
    assert before==sha(src)==sha(dst);pins[str(src)]=before

def common_environment(root):
    env={k:os.environ[k] for k in ['SystemRoot','WINDIR','COMSPEC','PATH','PATHEXT'] if k in os.environ}
    env.update(DSH_HOME=str(root/'home'),DSH_AGENTS_HOME=str(root/'agents_home'),DSH_TELEMETRY_MODE='DISABLED',
               HOME=str(root/'user'),USERPROFILE=str(root/'user'),APPDATA=str(root/'user/appdata'),LOCALAPPDATA=str(root/'user/localappdata'),
               TMP=str(root/'tmp'),TEMP=str(root/'tmp'),XDG_CACHE_HOME=str(root/'cache'),PYTHONDONTWRITEBYTECODE='1',PYTHONUTF8='1')
    return env

def public_s10(target,pins):
    source=WS/'graduation-datasets/chapter03_simulation_tasks/benchmark/case_reviews/Fouchier2020-Ground-RP80'
    initial=json.loads((source/'staged_S10_v1/initial_state.json').read_text(encoding='utf-8'))
    pins[str(source/'staged_S10_v1/initial_state.json')]=sha(source/'staged_S10_v1/initial_state.json')
    conditions={'id':'C3-S10-DEV-v2','identity':'new public development task based on admitted S10; not frozen accuracy benchmark',
      'source':{'radius_m':initial['source_anchor']['radius_m'],'pressure_absolute_pa':initial['source_anchor']['pressure_absolute_Pa'],
                'density_kg_m3':initial['conditional_closure']['hemisphere']['density_kg_m3'],'temperature_K':initial['conditional_closure']['hemisphere']['temperature_K']},
      'ambient':initial['conditional_closure']['ambient'],'gas_model':{'gamma':1.35,'R_J_kg_K':287,'Cv_J_kg_K':820},
      'geometry':{'axial_x_m':[0,1.4],'radial_extent_m':1.4,'wedge_degrees':5,'ground':'x=0',
                  'axial_grading_length_cells_ratio':[[.06,60,1],[.30,120,1],[1.04,120,6]],
                  'radial_grading_length_cells_ratio':[[.04,40,1],[.76,380,1],[.60,100,3]]},
      'probe_locations_m':[[0,.35,0],[0,.475,0],[0,.725,0]],'sampling':'patchProbes on ground, static p, every timestep',
      'end_time_s':.00301,'metric_window_s':[0,.003],'deltaT':1e-8,'maxCo':.2,'maxDeltaT':1e-6,
      'initialization':'setFields sphereToCell centre (0 0 0), prescribed source p/T/rho, U zero; preserve actual initialized fields',
      'constraints':'fixed conditional ideal-gas reconstruction; not calibrated experimental accuracy; no physics or grid changes to obtain pass',
      'accuracy_status':'pending','resource_limits':'operator binding and new scoped budget required'}
    write(target/'conditions.json',conditions)
    for name in ['constant/phaseProperties','system/fvSchemes','system/fvSolution']:
        copy(source/'staged_S10_v1/case'/name,target/'materials'/name,pins)
    # v2 follows reviewed job 8953576, equally in both arms.
    scheme=target/'materials/system/fvSchemes'
    scheme.write_text(scheme.read_text(encoding='utf-8').replace('reconstruct(U) upwind','reconstruct(U) vanLeerV').replace(' upwind',' vanLeer'),encoding='utf-8')
    write(target/'numerics_provenance.json',{'version':'v2','base':'staged_S10_v1',
        'change':'rho/p/e/speedOfSound vanLeer; U vanLeerV; other supplied entries unchanged',
        'development_evidence':'job 8953576; implementation choice, not prediction validation',
        'disclosure':'known successful development configuration, both arms; not unseen'})
    (target/'request.md').write_text('''# S10 地面半球压缩源仿真开发任务
从空payload/case开始，用blastFoam/OpenFOAM9完成conditions.json所规定的条件性模型。
本任务固定给出三份材料/离散字典，两臂均可直接复制；其余case、运行脚本、采样与交付由agent完成。
这是根据已入选场景制定的公开开发任务，不声称原论文全部热状态已确认，也不做实验误差通过判定。
几何为沿x轴的5度wedge，x=0为反射地面；网格为300×520×1。按JSON分段长度、格数、膨胀比生成。
p/T/rho的ground与outlet为zeroGradient，U的ground为noSlip、outlet为zeroGradient，front/back为wedge；U初始为零。
使用静态网格、laminar，复制给定数值方法。初始空气和球形区域p/T/rho按条件设置，不能换成TNT/JWL或拟合参考峰值。
控制设置按JSON，保留初始及最终场；writeInterval=0.00301，timePrecision=14，writePrecision=12。
所有网格、初始化、checkMesh、求解和计算型后处理经共同集群底座在分配节点执行。
在三个ground测点逐时间步采样绝对静压p。交付原生时程与完整时间轴CSV，超压=p-100000Pa；计算[0,0.003]s峰值、最早峰时和全窗正超压面积，缺窗不外推。
交付payload/case、run_case.sh、完整日志、pressure.csv、metrics.json、压力图和绘图源码、report.md、运行/版本/资源回执。
所有失败与重试保留并计成本。异常时按条件和运行权限报告，不改物理条件或求解器；失败报告不是仿真成功。
不要读取审核图、参考峰值、评分代码、原始参考case或其他运行。公共资料仅限task和共同原始语料入口。
''',encoding='utf-8')

def prepare(destination,dump=False,scenario='S10'):
    destination=destination.resolve()
    if not destination.is_relative_to(ARCHIVE.resolve()) or destination.exists():raise ValueError('new chapter3 archive directory required')
    destination.mkdir(parents=True);pins={}
    upstream=Path(os.environ.get('DSH_CHECKOUT',str(WS.parent/'deepseek-harness'))).resolve()
    identity=[upstream/'snapshot.json',upstream/'apps/cli/package.json'] if (upstream/'snapshot.json').exists() else [upstream/'pnpm-lock.yaml',upstream/'package.json']
    for p in [upstream/'apps/cli/lib/bin.js',*identity,PROJECT/'compatibility/dsh-version.json']:
        pins[str(p)]=sha(p)
    pins[str(HERE/'engineering_delivery.py')]=sha(HERE/'engineering_delivery.py')
    task=destination/'public_task';task.mkdir()
    if scenario=='S10':public_s10(task,pins)
    elif scenario=='S12':
        from public_s12 import prepare as prepare_s12
        pins[str(HERE/'public_s12.py')]=sha(HERE/'public_s12.py')
        prepare_s12(task,WS,pins,copy,write)
    else:raise ValueError('unsupported scenario')
    public_brief(task)
    # Both arms receive identical ordinary copies of original software sources.
    # No scorer, reference result, chapter-specific graph or private skill copied.
    source_roots=[]
    for name,source in [('manual',WS/'graduation-datasets/raw-corpus/blastfoam/blastFoam_user_guide/markdown'),
                        ('tutorials',WS/'graduation-datasets/raw-corpus/blastfoam/blastFoam_tutorials/blastFoam')]:
        target=destination/'public_sources'/name
        for item in sorted(source.rglob('*')):
            if item.is_symlink() or getattr(item.lstat(),'st_file_attributes',0)&1024:raise ValueError('source reparse path refused')
            if item.is_file():copy(item,target/item.relative_to(source),pins)
        source_roots.append(str(target))
    operator_records(destination/'operator_records')
    arms=[]
    for arm in ['general','professional']:
        root=destination/arm;workspace=root/'workspace';profile=root/'home/profiles/headless'
        for directory in [workspace,profile,root/'skills',root/'agents_home',root/'tmp',root/'cache',root/'user/appdata',root/'user/localappdata']:
            directory.mkdir(parents=True)
        shutil.copytree(task,workspace/'task')
        copy(HERE/'cluster_job.py',workspace/'common/cluster_job.py',pins)
        copy(HERE/'cluster_client.py',workspace/'common/cluster_client.py',pins)
        common='''# Common execution capabilities
Both arms use the same standard DSH file/shell tools and common/cluster_job.py.
Read task/request.md, conditions.json and delivery.md. Create payload/case and payload/run_case.sh.
The payload script runs from the dedicated remote run root; address files as payload/case, logs, etc.
For live operation call python common/cluster_client.py plan|stage|submit|status|collect.
The operator binds this client to one run; --payload payload is the default for staging.
The common cluster_job.py is the underlying bridge, not permission to open another SSH session.
No native computation on this Windows host or login node.
Live bindings, grants, runtime paths and budgets are operator inputs; currently absent. Do not generate your own approval.
At authorized launch, read common/limits.json for the identical request/output/time bounds and serial model concurrency.
Model providers are disabled in this inspection profile. SSH keys and API keys are never part of task files.
Raw documentation locations are in raw_sources.json and are identical for both arms. Do not access scoring/reference cases.
No framework completion marker, exit code or End line establishes task success. Follow the requested outputs and preserve failures.
'''
        (workspace/'OPERATIONS.md').write_text(common,encoding='utf-8')
        write(workspace/'raw_sources.json',{'read_only_roots':source_roots,
              'status':'identical hash-pinned ordinary copies; OS read-only enforcement still required for real run'})
        write(profile/'package.json',{'name':'c3-'+arm,'private':True,'dsh':{'profile':{'bundles':['@deepseek-ai/dsh-base','@deepseek-ai/dsh-headless'],'patchReload':'startup'}}})
        patch=[{'id':'agent-instructions','disabled':True}, {'id':'skill-filesystem','config':{'includeDefaultRoots':False,'customSkillDirs':[], 'bundledSkillDir':str(root/'skills'),'dshHome':str(root/'home'),'agentsHome':str(root/'agents_home'),'watch':False}}]
        patch += [{'id':key,'disabled':True} for key in ['llm-deepseek','llm-pi-ai','session-title-llm']]
        if arm=='professional':
            copy(HERE/'professional/skills/blastfoam-professional/SKILL.md',root/'skills/blastfoam-professional/SKILL.md',pins)
            copy(HERE/'professional/observe.py',workspace/'domain/observe.py',pins)
            copy(HERE/'pressure_observations.py',workspace/'domain/pressure_observations.py',pins)
            patch.append({'id':'system-prompt','config':{'persona':'You are a professional blast simulation agent using {{model}}. Work in {{cwd}}. Load skill blastfoam-professional, then complete the task using common execution capabilities. Do not require specialist subagents or legacy reports.'}})
        write(profile/'cordis.patch.yml',patch)
        prompt='Read OPERATIONS.md, task/request.md, task/conditions.json and task/delivery.md. Complete this task within the supplied operator grants and budgets; preserve all evidence and report actual completion without claiming unverified accuracy.'
        (root/'prompt.txt').write_text(prompt,encoding='utf-8')
        write(root/'launch.json',{'command':['node',str(upstream/'apps/cli/lib/bin.js'),'--profile','headless',prompt],'cwd':str(workspace),'DSH_HOME':str(root/'home'),'enabled':False,'reason':'model/compute grants, live bindings and isolation acceptance pending'})
        code=None
        if dump:
            result=subprocess.run(['node',str(upstream/'apps/cli/lib/bin.js'),'--profile','headless','--dump-config'],cwd=workspace,env=common_environment(root),capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=40)
            (root/'dump.yml').write_text(result.stdout,encoding='utf-8');(root/'dump.stderr.log').write_text(result.stderr,encoding='utf-8');code=result.returncode
            if code:raise RuntimeError('DSH dump failed; evidence retained')
        arms.append({'arm':arm,'home':str(root/'home'),'workspace':str(workspace),'dump_exit_code':code})
    changed=[p for p,h in pins.items() if sha(Path(p))!=h]
    if changed:raise RuntimeError('source changed during preparation')
    write(destination/'manifest.json',{'arms':arms,'source_sha256':pins,'real_run_allowed':False,'new_model_calls':0,'new_remote_calls':0,
          'shared_environment_changed':False,'historical_bundle_loaded':False,'OS_sandbox':False,
          'task_status':'public development formulation, declared scaffolding; reference answers/scorer not copied',
          'budget_status':'explicit paired model and compute budget not established'})
    return destination

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('destination',type=Path);p.add_argument('--dump-config',action='store_true');p.add_argument('--scenario',choices=['S10','S12'],default='S10');a=p.parse_args()
    print(prepare(a.destination,a.dump_config,a.scenario))
