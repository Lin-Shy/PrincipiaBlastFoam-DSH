"""Bounded transport recovery of the original calibration, without replacing evidence.

The inference protocol is unchanged. A separately hashed execution supplement
binds the retry implementation, waiting time, concurrency and eligible tasks.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import argparse, json, shutil, subprocess, sys
from models import WORK, EXPERIMENT, MODELS, encoded, sha, now, load_model, public_deployment
from transport_retry import RetryingClient, RetryPolicy, import_request

POINTER = EXPERIMENT/'release/planning/transport_retry.json'
GATE = EXPERIMENT/'release/planning/execution.json'
BASE = EXPERIMENT/'release/planning/run_protocol.json'
RECOVERABLE = {'outcome_unknown','http_result_unknown','deployment_halted','not_dispatched_model_halted'}
PREFIX = 'PrincipiaBlastFoam-DSH/experiments/chapter2/'
CHANGED = {PREFIX+n for n in ('runner.py','models.py')}
ADDED = {PREFIX+n for n in ('transport_retry.py','recover_transport.py','test_transport_retry.py')}
def read(p): return json.loads(p.read_text('utf-8'))
def write_new(p,v):
    p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('xb') as f:f.write(encoded(v))
def require(ok,msg):
    if not ok:raise ValueError(msg)

def recovery_root(h):return EXPERIMENT/'recoveries'/h[:12]
def task_folder(root,tid):return root/tid[:16]

def verify_overlay(base=None,*,check_current=True,overlay_sha256=None):
    from runner import source_bindings
    base=read(BASE) if base is None else base
    h=overlay_sha256 or read(POINTER)['overlay_sha256']
    frozen=EXPERIMENT/'release/frozen/transport_retry'/h
    require(sha((frozen/'manifest.json').read_bytes())==h,'Execution supplement hash mismatch')
    o=read(frozen/'manifest.json')
    require(o['base_protocol_sha256']==sha(encoded(base)),'Inference protocol changed')
    current=source_bindings();executed=o['implementation']
    if check_current:require(current==executed,'Retry implementation drift; prepare the next protocol before dispatch')
    require(set(executed)-set(base['implementation'])==ADDED,'Unexpected added generation code')
    require(set(base['implementation'])<=set(executed),'Removed generation implementation')
    for n,v in base['implementation'].items():
        require(n in CHANGED or executed[n]==v,'Inference implementation changed: '+n)
    # Only models.Client's persistence handling changed; payload/deployment logic
    # must still match the original source at the AST level.
    import ast
    original=EXPERIMENT/'release/frozen'/o['base_protocol_sha256']/'implementation'/PREFIX/'models.py'
    before={x.name:ast.dump(x,include_attributes=False) for x in ast.parse(original.read_text('utf-8')).body if isinstance(x,(ast.FunctionDef,ast.ClassDef)) and x.name!='Client'}
    after={x.name:ast.dump(x,include_attributes=False) for x in ast.parse((frozen/o['stored_implementation'][PREFIX+'models.py']).read_text('utf-8')).body if isinstance(x,(ast.FunctionDef,ast.ClassDef)) and x.name!='Client'}
    require(before==after,'Inference payload/deployment logic changed')
    for n,v in executed.items():require(sha((frozen/o['stored_implementation'][n]).read_bytes())==v,'Frozen supplement code drift')
    require(o['retry_policy']==RetryPolicy().public(),'Retry policy drift')
    return o

def preserve_current_materials(ph):
    r=WORK/'graduation-datasets/chapter02_knowledge_qa/open/review/calibration'
    folder=EXPERIMENT/'release/frozen'/ph/'calibration_materials'
    if folder.exists():
        saved=read(folder/'manifest.json')
        require(saved['protocol_sha256']==ph,'Preserved material identity mismatch')
        for n,v in saved['files'].items():require(sha((folder/saved['stored_files'][n]).read_bytes())==v,'Preserved material drift')
        return
    files=[r/n for n in ('calibration/packets.json','calibration/blank_labels.json','acceptance/packets.json','acceptance/blank_labels.json','index.html','README.md','GENERATION_REPORT.md')]
    files+=list((r/'administration').glob('*'))
    files += [EXPERIMENT/'release'/n for n in ('manifests/current.json','manifests/calibration_generation.json','planning/execution.json','validation/calibration_generation.json')]
    folder.mkdir(parents=True);hashes={};stored={}
    for i,p in enumerate(sorted(p for p in files if p.is_file())):
        name=p.relative_to(WORK).as_posix();dest=folder/f'payload/{i:04d}.data';dest.parent.mkdir(exist_ok=True)
        shutil.copyfile(p,dest);hashes[name]=sha(p.read_bytes());stored[name]=dest.relative_to(folder).as_posix()
        require(sha(dest.read_bytes())==hashes[name],'Archive copy mismatch')
    write_new(folder/'manifest.json',dict(schema='preserved_current_calibration_materials_v1',protocol_sha256=ph,files=hashes,stored_files=stored,
              reason='Preserve the current November 44-answer calibration and its partial receipts before authorized transport recovery; not a deleted old-experiment backup'))

def prepare_overlay(*,revise=False):
    from runner import source_bindings,environment
    previous=read(POINTER)['overlay_sha256'] if POINTER.exists() else None
    require(previous is None or revise,'Execution supplement exists; only an explicit --revise may prepare a replacement policy')
    gate=read(GATE);require(not gate['formal_generation_authorized'] and not gate['allowed_stages'],'Close normal dispatch first')
    require(not gate.get('transport_recovery_authorized'),'Cannot prepare while transport recovery is active')
    p=read(BASE);ph=sha(BASE.read_bytes())
    review=WORK/'graduation-datasets/chapter02_knowledge_qa/open/review/calibration'
    receipt=read(review/'administration/generation_check.json')
    require(receipt['protocol_sha256']==ph and receipt['answered']==44 and receipt['unknown']==15 and receipt['interrupted']==1,'Expected the current partial calibration')
    for n,h in receipt['files'].items():require(sha((EXPERIMENT/n).read_bytes())==h,'Original run drift')
    selected=[]
    for task in read(EXPERIMENT/'release/manifests/calibration_generation.json')['selected_tasks']:
        result=EXPERIMENT/'runs'/ph/task['model']/task['task_id']/'result.json'
        row=read(result)
        if row['status'] in RECOVERABLE:selected.append(dict(task=task,result=result.relative_to(EXPERIMENT).as_posix(),result_sha256=sha(result.read_bytes())))
    require(len(selected)==16,'Exactly 16 transport tasks expected')
    require(len({e['task']['task_id'][:16] for e in selected})==16,'Short task path collision')
    require(all(l['record']['status']=='pending' and l['reviewer'] is None for l in read(review/'calibration/blank_labels.json')['labels']),'Human labels already exist')
    preserve_current_materials(ph)
    implementation=source_bindings()
    o=dict(schema='chapter2_transport_execution_supplement_v1',prepared_utc=now(),base_protocol_sha256=ph,
           implementation=implementation,stored_implementation={n:f'implementation/{i:03d}.py' for i,n in enumerate(implementation)},environment=environment(),retry_policy=RetryPolicy().public(),
           dispatch_concurrency={m:min(load_model(m).concurrency,20 if m=='qwen3-14b' else 8) for m in MODELS},
           selected_tasks=selected,original_run_files=receipt['files'],
           authorization='User: 因为超时/中断而失败的记录需要实现自动重试',
           scope='only 16 original calibration transport failures; no full matrix, acceptance or judges',
           inference_change=False,successful_answers_repeated=False,model_output_retries=False,
           previous_execution_overlay_sha256=previous,path_layout='recoveries/overlay_sha256_prefix12/model/task_sha256_prefix16')
    raw=encoded(o);h=sha(raw);folder=EXPERIMENT/'release/frozen/transport_retry'/h;folder.mkdir(parents=True,exist_ok=False)
    (folder/'manifest.json').write_bytes(raw)
    for n,v in o['implementation'].items():
        dest=folder/o['stored_implementation'][n];dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(WORK/n,dest)
    POINTER.write_bytes(encoded(dict(schema='chapter2_transport_overlay_pointer_v1',overlay_sha256=h,base_protocol_sha256=ph)))
    gate.update(transport_recovery_authorized=True,transport_overlay_sha256=h,allowed_recovery_task_ids=sorted(x['task']['task_id'] for x in selected),transport_recovery_task_count=16)
    GATE.write_bytes(encoded(gate));verify_overlay(p)
    return dict(overlay_sha256=h,base_protocol_sha256=ph,eligible_tasks=16,retry_policy=o['retry_policy'])

def authorize():
    gate=read(GATE)
    if gate.get('transport_recovery_authorized') is not True:raise PermissionError('Transport recovery is closed')
    o=verify_overlay();h=read(POINTER)['overlay_sha256']
    require(gate.get('transport_overlay_sha256')==h,'Recovery authorization mismatch')
    require(set(gate.get('allowed_recovery_task_ids',[]))=={x['task']['task_id'] for x in o['selected_tasks']},'Recovery task scope mismatch')
    from runner import verify_protocol
    verify_protocol()
    return o,h

def recover_one(entry,o,h,root,questions,client,counter,deployment):
    from runner import run_one
    t=entry['task'];source=EXPERIMENT/entry['result'];require(sha(source.read_bytes())==entry['result_sha256'],'Original result changed')
    target=task_folder(root,t['task_id']);target.mkdir(parents=True,exist_ok=True)
    if (target/'result.json').exists():return read(target/'result.json')['status']
    for original in sorted((source.parent/'requests').glob('*.json')):
        import_request(original,target/'requests'/original.name)
    # The dispatcher accepts an explicit short storage key while retaining the
    # complete task identity in every claim and result.
    return run_one(t,questions,client,counter,deployment,root,o['base_protocol_sha256'],storage_key=t['task_id'][:16])

def worker(model):
    from runner import model_lock,atomic_new
    from tokenization import ChatCounter
    o,h=authorize();rows=[e for e in o['selected_tasks'] if e['task']['model']==model]
    require(rows,'No transport tasks for this model')
    with model_lock(model):
        d=load_model(model);counter=ChatCounter(model);client=RetryingClient(d,concurrency=o['dispatch_concurrency'][model])
        import runtime
        from chapter2_knowledge_input_guard import install
        public=[WORK/'graduation-datasets/chapter02_knowledge_qa'/part/'model/questions.json' for part in ('open','objective')]
        guard=install(public_question_files=public)
        questions={part:{q['id']:q for q in read(public[i])} for i,part in enumerate(('open','objective'))}
        root=recovery_root(h)/model;root.mkdir(parents=True,exist_ok=True)
        if not (root/'input_guard.json').exists():atomic_new(root/'input_guard.json',guard)
        statuses=[]
        with ThreadPoolExecutor(max_workers=o['dispatch_concurrency'][model]) as pool:
            futures=[pool.submit(recover_one,e,o,h,root,questions,client,counter,d) for e in rows]
            for f in as_completed(futures):statuses.append(f.result())
        from collections import Counter
        summary=dict(model=model,task_count=len(rows),statuses=dict(Counter(statuses)),halted=client.halted.is_set(),execution_overlay_sha256=h)
        (root/'summary.json').write_bytes(encoded(summary));return summary

def main():
    a=argparse.ArgumentParser(description=__doc__);a.add_argument('command',choices=['prepare','verify','run','worker']);a.add_argument('--model',choices=MODELS);a.add_argument('--revise',action='store_true');v=a.parse_args()
    if v.command=='prepare':print(json.dumps(prepare_overlay(revise=v.revise)));return
    if v.command=='verify':verify_overlay();print('Execution supplement and frozen inference bindings verified; no requests');return
    if v.command=='worker':print(json.dumps(worker(v.model)));return
    o,h=authorize();models=sorted({e['task']['model'] for e in o['selected_tasks']})
    def one(m):
        r=subprocess.run([sys.executable,'-X','utf8',str(Path(__file__).resolve()),'worker','--model',m],capture_output=True,text=True,encoding='utf-8')
        # Any failure is surfaced by type/exit code, without dumping private service addresses.
        return dict(model=m,exit_code=r.returncode,summary=json.loads(r.stdout) if r.returncode==0 else None)
    try:
        with ThreadPoolExecutor(max_workers=3) as pool:print(json.dumps(list(pool.map(one,models))))
    finally:
        gate=read(GATE);gate.update(transport_recovery_authorized=False,transport_recovery_dispatch_ended_utc=now());GATE.write_bytes(encoded(gate))

if __name__=='__main__':main()
