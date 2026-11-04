"""Current batch dispatcher. prepare/verify are offline; run requires a frozen authorization.

One process per model, one shared client/queue across question parts and methods.
Completed answers are immutable; transport retries preserve every attempt.
"""
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
import argparse,collections,json,subprocess,sys,importlib.metadata
from contextlib import contextmanager
from models import WORK,EXPERIMENT,MODELS,Client,load_model,public_deployment,encoded,sha,now
from matrix import DATASET,prepare as prepare_matrix,tasks
from tokenization import ChatCounter
from transport_retry import RetryingClient,RetryPolicy

HERE=Path(__file__).resolve().parent
PROTOCOL=EXPERIMENT/'release/planning/run_protocol.json'
AUTHORIZATION=EXPERIMENT/'release/planning/execution.json'

@contextmanager
def model_lock(model,root=None):
    folder=Path(root) if root else EXPERIMENT/'runtime_locks';folder.mkdir(parents=True,exist_ok=True)
    with (folder/(model+'.lock')).open('a+b') as handle:
        if handle.tell()==0:handle.write(b'0');handle.flush()
        handle.seek(0)
        if sys.platform=='win32':
            import msvcrt
            msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        try:yield
        finally:
            handle.seek(0)
            if sys.platform=='win32':msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
            else:fcntl.flock(handle,fcntl.LOCK_UN)

def source_bindings():
    files=set(HERE.rglob('*.py'))|set((HERE.parent/'retrieval_method').glob('*.py'))|set((HERE.parents[1]/'src/principia_core/retrieval').rglob('*.py'))
    return {p.relative_to(WORK).as_posix():sha(p.read_bytes()) for p in sorted(files)}

def environment():
    packages={}
    for name in ('torch','transformers','tokenizers','jinja2','numpy','onnxruntime','regex'):
        try:packages[name]=importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:packages[name]='not_installed'
    return dict(python=sys.version,packages=packages)

def prepare():
    workflow=EXPERIMENT/'release/planning/review_workflow.json'
    if workflow.exists() and json.loads(workflow.read_text('utf-8')).get('acceptance_cancelled'):
        raise PermissionError('Calibration artifacts are sealed; use formal_experiment.py freeze/verify')
    prepare_matrix()
    counters={m:ChatCounter(m).public() for m in MODELS}
    from human_review import verify_plan
    verify_plan()
    # Maintenance-side selection exports ONLY task IDs into the run protocol.
    # Generation never reads the review workspace or its Gold/labels.
    panel=json.loads((DATASET/'open/review/calibration/administration/sample_mapping.json').read_text('utf-8'))
    panels={phase:sorted(r['task']['task_id'] for r in panel['samples'] if r['phase']==phase) for phase in ('calibration','acceptance')}
    assert len(panels['calibration'])==len(panels['acceptance'])==60 and not set(panels['calibration'])&set(panels['acceptance'])
    valid_ids={r['task_id'] for r in tasks()}
    assert set(panels['calibration']+panels['acceptance'])<=valid_ids
    protocol=dict(schema='chapter2_current_run_v1',prepared_utc=now(),status='prepared_not_dispatched',
        dataset_sha256=json.loads((DATASET/'binding.json').read_text('utf-8'))['dataset_sha256'],
        public_questions={p:sha((DATASET/p/'model/questions.json').read_bytes()) for p in ('open','objective')},
        resources_sha256=sha((EXPERIMENT/'data/resources/manifest.json').read_bytes()),
        design_sha256=sha((WORK/'graduation-thesis-materials/graduation-research/chapters/chapter02.md').read_bytes()),
        implementation=source_bindings(),environment=environment(),tokenizers=counters,deployments={m:public_deployment(load_model(m)) for m in MODELS},generation_panels=panels,
        budgets={'S':6000,'M':12000,'L':24000},primary_tier='M',report_all_tiers=True,
        context_tokens=32768,output_tokens_per_request=2048,total_token_caps=None,
        agentic_tool_calls=12,agentic_characters_per_call=6000,single_pass_fixed_raw_question=True,
        temperature=0,automatic_retries=2,transport_retry_policy=RetryPolicy().public(),
        dispatch_concurrency={m:min(load_model(m).concurrency,20 if m=='qwen3-14b' else 8) for m in MODELS},
        unknown_outcome='retry_identical_request_up_to_limit_then_halt_model',
        malformed_or_truncated_answer='retain_as_failed_no_content_retry',
        resume='skip_terminal_results; resume_interrupted_claim_by_replaying_saved_prefix_and_retrying_unfinished_request; never_content_retry',
        direct_shared_between_modes=True,task_count=51300,configurations=171,
        answer_only_inputs=['exact two public id/question files','fixed original corpus','method resources','model tokenizer'],
        formal_generation_started=False)
    PROTOCOL.write_bytes(encoded(protocol))
    # Re-preparing can never silently enable dispatch.
    AUTHORIZATION.write_bytes(encoded(dict(schema='chapter2_execution_authorization_v1',formal_generation_authorized=False,
        allowed_stages=[],protocol_sha256=sha(PROTOCOL.read_bytes()),technical_checks_required=True,reason='User requested preparation only, no formal batch.')))
    return protocol

def verify_protocol():
    p=json.loads(PROTOCOL.read_text('utf-8'))
    if p['environment']!=environment():raise ValueError('Python/dependency environment drift')
    if p['implementation']!=source_bindings():
        from recover_transport import verify_overlay
        verify_overlay(p)
    for part,h in p['public_questions'].items():
        if sha((DATASET/part/'model/questions.json').read_bytes())!=h:raise ValueError('Question drift')
    if sha((EXPERIMENT/'data/resources/manifest.json').read_bytes())!=p['resources_sha256']:raise ValueError('Resource drift')
    for name,h in json.loads((EXPERIMENT/'data/resources/manifest.json').read_text('utf-8'))['files'].items():
        if sha((EXPERIMENT/'data/resources'/name).read_bytes())!=h:raise ValueError('Resource content drift: '+name)
    for m in MODELS:
        if ChatCounter(m).public()!=p['tokenizers'][m]:raise ValueError('Tokenizer drift')
        if public_deployment(load_model(m))!=p['deployments'][m]:raise ValueError('Deployment drift')
    if sha((WORK/'graduation-thesis-materials/graduation-research/chapters/chapter02.md').read_bytes())!=p['design_sha256']:raise ValueError('Design drift')
    return p

def authorize_dispatch(stage='all'):
    workflow=EXPERIMENT/'release/planning/review_workflow.json'
    if workflow.exists() and json.loads(workflow.read_text('utf-8')).get('acceptance_cancelled'):
        raise PermissionError('Legacy staged dispatch is retired; use formal_experiment.py')
    # Read and validate this before constructing any client or opening a service.
    a=json.loads(AUTHORIZATION.read_text('utf-8'))
    if a.get('formal_generation_authorized') is not True:raise PermissionError('Formal generation is not authorized; no requests sent')
    if stage not in a.get('allowed_stages',[]):raise PermissionError('Requested stage is outside the generation authorization')
    if a.get('protocol_sha256')!=sha(PROTOCOL.read_bytes()):raise ValueError('Authorization belongs to a different protocol')
    p=verify_protocol()
    checks=json.loads((EXPERIMENT/'release/validation/preparation.json').read_text('utf-8'))
    if checks.get('passed') is not True or checks.get('protocol_sha256')!=sha(PROTOCOL.read_bytes()):raise ValueError('Current preparation checks required')
    return p

def atomic_new(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('xb') as f:f.write(encoded(value))

def run_one(task,questions,client,counter,deployment,root,binding,*,storage_key=None):
    folder=root/(storage_key or task['task_id']);folder.mkdir(parents=True,exist_ok=True)
    done=folder/'result.json';claim=folder/'claim.json'
    if done.exists():
        r=json.loads(done.read_text('utf-8'))
        if r['task']!=task or r['protocol_sha256']!=binding:raise ValueError('Existing result binding mismatch')
        return 'already_terminal'
    if claim.exists():
        if not getattr(client,'can_resume',False):raise RuntimeError('Unresolved task claim: durable retry client required')
        saved=json.loads(claim.read_text('utf-8'))
        if saved['task']!=task or saved['protocol_sha256']!=binding:raise ValueError('Interrupted claim binding mismatch')
        resumes=folder/'resumes';resumes.mkdir(exist_ok=True)
        atomic_new(resumes/(f'{len(list(resumes.glob("*.json"))):03d}.json'),dict(resumed_utc=now(),task=task,protocol_sha256=binding))
    if client.halted.is_set():return 'not_dispatched_model_halted'
    if not claim.exists():atomic_new(claim,dict(task=task,protocol_sha256=binding,claimed_utc=now()))
    from runtime import tools_for,run_question
    try:
        tools=tools_for(task['method'],task['mode'],task['budget'])
        result=run_question(questions[task['part']][task['id']],task['mode'],task['method'],task['budget'],tools,client,deployment,counter,folder/'requests')
    except Exception as exc:
        # Never turn a local bug into a fresh generation attempt. Raw requests survive.
        result=dict(status='runner_error',error_type=type(exc).__name__,answer=None)
        client.halted.set()
    atomic_new(done,dict(task=task,protocol_sha256=binding,ended_utc=now(),**result))
    if result['status'] in {'tokenizer_mismatch','provider_context_violation','usage_unknown','model_identity_mismatch','outcome_unknown','http_result_unknown'}:client.halted.set()
    return result['status']

def _worker(model,stage='all'):
    p=authorize_dispatch(stage);binding=sha(PROTOCOL.read_bytes())
    d=load_model(model);counter=ChatCounter(model)
    retry=p.get('transport_retry_policy')
    if retry is None:
        from recover_transport import verify_overlay
        overlay=verify_overlay(p);retry=overlay['retry_policy'];concurrency=overlay['dispatch_concurrency'][model]
    else:concurrency=p['dispatch_concurrency'][model]
    policy=RetryPolicy(retry['max_attempts'],retry['timeout_seconds'],tuple(retry['backoff_seconds']))
    client=RetryingClient(d,policy,concurrency=concurrency)
    # Imports may load numerical libraries. After this point no process launch and
    # no Gold/review reads are permitted, even from dependencies.
    import runtime
    from chapter2_knowledge_input_guard import install
    rows=sorted([r for r in tasks() if r['model']==model],key=lambda r:sha(('20261103'+r['task_id']).encode()))
    if stage!='all':
        selected=set(p['generation_panels']['calibration']+p['generation_panels']['acceptance']) if stage=='review120' else set(p['generation_panels'][stage])
        rows=[r for r in rows if r['task_id'] in selected]
    public=[DATASET/part/'model/questions.json' for part in ('open','objective')]
    guard=install(public_question_files=public)
    questions={part:{q['id']:q for q in json.loads((DATASET/part/'model/questions.json').read_text('utf-8'))} for part in ('open','objective')}
    root=EXPERIMENT/'runs'/binding/model;root.mkdir(parents=True,exist_ok=True)
    for claim in root.glob('*/claim.json'):
        result=claim.with_name('result.json')
        if result.exists() and json.loads(result.read_text('utf-8'))['status'] in {'outcome_unknown','http_result_unknown','usage_unknown','runner_error'}:
            raise RuntimeError('An existing request needs reconciliation before model dispatch; no new requests sent')
    if not (root/'input_guard.json').exists():atomic_new(root/'input_guard.json',guard)
    counts=collections.Counter()
    # Submit a bounded window rather than all 17,100 tasks; stop on ambiguity.
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        iterator=iter(rows);pending=set()
        while True:
            while len(pending)<concurrency and not client.halted.is_set():
                task=next(iterator,None)
                if task is None:break
                pending.add(pool.submit(run_one,task,questions,client,counter,d,root,binding))
            if not pending:break
            f=next(as_completed(pending));pending.remove(f)
            try:counts[f.result()]+=1
            except Exception:client.halted.set();counts['reconciliation_required']+=1
    summary=dict(model=model,stage=stage,protocol_sha256=binding,counts=dict(counts),halted=client.halted.is_set(),planned_tasks=len(rows))
    (root/('dispatch_summary_'+stage+'.json')).write_bytes(encoded(summary));return summary

def worker(model,stage='all'):
    authorize_dispatch(stage)
    with model_lock(model):return _worker(model,stage)

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=['prepare','verify','run','worker']);parser.add_argument('--model',choices=MODELS)
    parser.add_argument('--stage',choices=['all','calibration','acceptance','review120'],default='all')
    a=parser.parse_args()
    if a.command=='prepare':print(json.dumps(dict(protocol_sha256=sha(encoded(prepare())),formal_generation_started=False)));return
    if a.command=='verify':verify_protocol();print('Protocol bindings verified; no requests made');return
    if a.command=='worker':
        if not a.model:parser.error('--model required')
        print(json.dumps(worker(a.model,a.stage)));return
    authorize_dispatch(a.stage)
    def one(m):
        r=subprocess.run([sys.executable,str(Path(__file__).resolve()),'worker','--model',m,'--stage',a.stage],capture_output=True,text=True)
        return dict(model=m,exit_code=r.returncode) # stderr may include local paths; retain locally, never credentials.
    with ThreadPoolExecutor(max_workers=3) as pool:print(json.dumps(list(pool.map(one,MODELS))))

if __name__=='__main__':main()
