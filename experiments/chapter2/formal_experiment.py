"""Authorized full experiment, isolated generation and scoring, durable resume.

The extra human acceptance panel is cancelled. Calibration artifacts stay sealed.
Generation workers never load scoring data; the scoring process never generates answers.
"""
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from collections import Counter, defaultdict
from copy import deepcopy
import argparse
import json
import os
import subprocess
import sys
import threading
import time

from models import WORK, EXPERIMENT, MODELS, encoded, sha, now, load_model, public_deployment
from transport_retry import RetryingClient, RetryPolicy, atomic, storage_path, request_lock

HERE=Path(__file__).resolve().parent
DATA=WORK/'graduation-datasets/chapter02_knowledge_qa'
REVIEW=DATA/'open/review/calibration'
POINTER=EXPERIMENT/'release/planning/formal_experiment.json'
AUTH=EXPERIMENT/'release/planning/formal_execution.json'
WORKFLOW=EXPERIMENT/'release/planning/review_workflow.json'
JUDGES=('gpt_sol','deepseek_flash')
UNKNOWN={'not_run','started','in_flight','outcome_unknown','http_result_unknown','usage_unknown','runner_error','deployment_halted','not_dispatched_model_halted','response_persistence_error','http_rejected','invalid_response','service_configuration_error','tokenizer_mismatch','provider_context_violation','output_budget_violation','model_identity_mismatch'}
FATAL={'runner_error','usage_unknown','invalid_response','service_configuration_error','tokenizer_mismatch','provider_context_violation','output_budget_violation','model_identity_mismatch','response_persistence_error','input_binding_mismatch'}
USER_AUTHORIZATION='负责人：取消额外60份验收，沿用现有双裁判和人工评分；完成冻结、评分入口及重试恢复检查，核验后直接启动三模型全量，客观200＋开放100。'


def read(path):return json.loads(storage_path(path).read_text(encoding='utf-8'))
def digest(path):return sha(storage_path(path).read_bytes())
def require(ok,message):
    if not ok:raise ValueError(message)
def new(path,value):
    path=storage_path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('xb') as f:f.write(encoded(value))
def state(path,value):
    path=storage_path(path);path.parent.mkdir(parents=True,exist_ok=True);atomic(path,value)
def relative(path):return Path(str(path).removeprefix('\\\\?\\')).relative_to(WORK).as_posix()


def active():
    pointer=read(POINTER);manifest=EXPERIMENT/pointer['manifest'];frozen=read(manifest)
    require(sha(encoded(frozen['protocol']))==pointer['protocol_sha256']==frozen['protocol_sha256'],'Formal protocol identity mismatch')
    return pointer['protocol_sha256'],frozen['protocol'],manifest.parent,EXPERIMENT/pointer['output_root']


def source_bindings():
    from runner import source_bindings as sources
    return sources()


def judge_profile(judge):
    from judge_calibration import calibration_profile
    return calibration_profile(judge,8192)


def generation_proof():
    """Compare actual inference dependencies to the executed transport supplement."""
    old=read(EXPERIMENT/'release/planning/run_protocol.json')
    overlay_id=read(EXPERIMENT/'release/planning/transport_retry.json')['overlay_sha256']
    overlay=read(EXPERIMENT/'release/frozen/transport_retry'/overlay_id/'manifest.json')
    names=[name for name in overlay['implementation'] if '/backends/' in name or '/retrieval_method/' in name or '/src/principia_core/retrieval/' in name or Path(name).name in {'runtime.py','models.py','structured_actions.py','tokenization.py'}]
    for name in names:require(digest(WORK/name)==overlay['implementation'][name],'Generation dependency changed: '+name)
    from tokenization import ChatCounter
    for model in MODELS:
        require(ChatCounter(model).public()==old['tokenizers'][model],'Adoption tokenizer mismatch')
        require(public_deployment(load_model(model))==old['deployments'][model],'Adoption deployment mismatch')
    require(digest(EXPERIMENT/'data/resources/manifest.json')==old['resources_sha256'],'Adoption resource mismatch')
    return dict(base_protocol_sha256=digest(EXPERIMENT/'release/planning/run_protocol.json'),transport_overlay_sha256=overlay_id,
                unchanged_inference_dependencies={n:overlay['implementation'][n] for n in names},
                orchestration_change='Separate full-run entry; task-local bounded retries; no inference prompt/tool/budget/temperature changes',
                adopt_all_60_including_generation_and_judge_failures=True)


def adoption_rows():
    from recover_transport import recovery_root, task_folder
    mapping=[r for r in read(REVIEW/'administration/sample_mapping.json')['samples'] if r['phase']=='calibration']
    packets={p['sample_id']:p for p in read(REVIEW/'calibration/packets.json')['samples']}
    base=digest(EXPERIMENT/'release/planning/run_protocol.json')
    overlay_id=read(EXPERIMENT/'release/planning/transport_retry.json')['overlay_sha256']
    selected={r['task']['task_id'] for r in read(EXPERIMENT/'release/frozen/transport_retry'/overlay_id/'manifest.json')['selected_tasks']}
    trial=read(EXPERIMENT/'release/planning/judge_calibration.json')
    result=[]
    for row in mapping:
        task=row['task'];tid=task['task_id'];packet=packets[row['sample_id']]
        source=(task_folder(recovery_root(overlay_id)/task['model'],tid) if tid in selected else EXPERIMENT/'runs'/base/task['model']/tid)/'result.json'
        value=read(source)
        require(value['task']==task and value['status'] not in UNKNOWN,'Unresolved calibration generation cannot be silently adopted')
        require((value['status']!='answered')==packet['generation_failed'],'Adoption failure status differs')
        if value['status']=='answered':require(value['answer']==packet['answer'],'Adoption answer differs')
        scores={j:EXPERIMENT/trial['output_root']/j/row['sample_id']/'result.json' for j in JUDGES}
        result.append(dict(task=task,sample_id=row['sample_id'],source=relative(source),source_sha256=digest(source),
                           judge_sources={j:dict(path=relative(p),sha256=digest(p)) for j,p in scores.items()}))
    require(len(result)==60,'Adoption cohort incomplete')
    return result


def freeze():
    require(not POINTER.exists(),'Existing formal freeze must not be replaced')
    from runner import environment
    from matrix import tasks, configurations
    from tokenization import ChatCounter
    from judge_calibration import prompt_text, public_profile, verify as verify_calibration
    from judge_contract import schema
    rows=list(tasks());require(len(rows)==51300 and len({r['task_id'] for r in rows})==51300,'Matrix identity mismatch')
    _,calibration,_,_=verify_calibration(current=False)
    require(sha(prompt_text().encode())==calibration['prompt_sha256'] and schema()==calibration['output_schema'],'Calibrated judging rules changed')
    for j in JUDGES:require(public_profile(judge_profile(j))==calibration['profiles'][j],'Calibrated effective profile changed')
    proof=generation_proof();adopt=adoption_rows()
    public={relative(DATA/part/'model/questions.json'):digest(DATA/part/'model/questions.json') for part in ('open','objective')}
    scoring=[DATA/'open/scoring/annotations.json',DATA/'open/scoring/evidence.json',DATA/'objective/scoring/annotations.json',REVIEW/'calibration/calibration_completed_human_labels.json']
    static=dict(schema='chapter2_formal_full_v1',frozen_utc=now(),authorization=USER_AUTHORIZATION,
                dataset_sha256=read(DATA/'binding.json')['dataset_sha256'],public_questions=public,
                scoring_inputs={relative(p):digest(p) for p in scoring},resources_manifest_sha256=digest(EXPERIMENT/'data/resources/manifest.json'),
                design=dict(path='graduation-thesis-materials/graduation-research/chapters/chapter02.md',sha256=digest(WORK/'graduation-thesis-materials/graduation-research/chapters/chapter02.md')),
                implementation=source_bindings(),environment=environment(),task_count=51300,configurations=171,parts=dict(objective=34200,open=17100),
                tasks_sha256=sha(encoded(rows)),models={m:public_deployment(load_model(m)) for m in MODELS},tokenizers={m:ChatCounter(m).public() for m in MODELS},
                generation=dict(query_characters_max=512,output_tokens=2048,context_tokens=32768,temperature=0,evidence_characters=dict(S=6000,M=12000,L=24000),
                                primary_tier='M',report_all_tiers=True,agentic_actions_max=12,agentic_evidence_per_call=6000,direct_shared_between_modes=True,
                                concurrency={m:min(load_model(m).concurrency,20 if m=='qwen3-14b' else 8) for m in MODELS}),
                judging=dict(profiles={j:public_profile(judge_profile(j)) for j in JUDGES},concurrency=dict(gpt_sol=2,deepseek_flash=1),
                             prompt_sha256=sha(prompt_text().encode()),schema=schema(),output_tokens=8192,input_tokens=24576,
                             aggregation='compute_each_judge_EAS_then_mean_exactly_two; no_single_judge_fallback',rubric_changed=False),
                retry=dict(**RetryPolicy().public(),scope='per_request_per_task; exhausted_task_unknown_does_not_halt_other_tasks',
                           process_restart='resume_saved_responses_and_attempt_ledger; never_reset_attempt_count; never_retry_content'),
                acceptance=dict(status='cancelled_by_owner',additional_human_answers=0,not_required_for_dispatch=True,not_claimed_passed=True),
                calibration=dict(status='adopted_as_basis_for_dual_judge_use',human_reference_count=60,
                                 protocol_sha256=read(EXPERIMENT/'release/planning/judge_calibration.json')['protocol_sha256'],
                                 old_thresholds='retain_as_historical_calibration_diagnostics_not_an_extra_dispatch_gate'),
                adoption_proof=proof,adoptions=adopt,
                scoring_policy=dict(generation_failure='fixed_zero',transport_or_usage_unknown='unknown_with_fixed_denominator_bounds',
                                    malformed_judge='missing_no_content_retry',not_run='unknown_distinct_from_zero',
                                    objective='deterministic_explicit_final_answer_only',open='unchanged_K_F_A_arithmetic_and_geometric_EAS_and_Strict'),
                statistics=dict(primary='question-paired comparisons per model; objective accuracy and open EAS separately',
                                clustering='question IDs; shared knowledge groups sensitivity',report_all_budgets_and_failures=True))
    ph=sha(encoded(static));root=storage_path(EXPERIMENT/'release/frozen/formal_experiment'/ph);root.mkdir(parents=True,exist_ok=False)
    for name,h in static['implementation'].items():
        target=root/'implementation'/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes((WORK/name).read_bytes());require(digest(target)==h,'Freeze copy mismatch')
    new(root/'manifest.json',dict(protocol_sha256=ph,protocol=static));new(root/'tasks.json',rows)
    for name in static['scoring_inputs']:
        target=root/'inputs'/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes((WORK/name).read_bytes())
    (root/'judge_prompt.txt').write_text(prompt_text(),encoding='utf-8')
    state(POINTER,dict(protocol_sha256=ph,manifest=relative(root/'manifest.json').split('chapter2_retrieval/',1)[1],output_root=f'formal/{ph[:12]}',status='frozen_checks_pending'))
    state(AUTH,dict(protocol_sha256=ph,authorized=False,source=USER_AUTHORIZATION,allowed_roles=['generation','scoring'],acceptance_authorized=False))
    _,_,_,out=active();out.mkdir(parents=True,exist_ok=True)
    for item in adopt:
        task=item['task'];tid=task['task_id'];value=read(WORK/item['source'])
        value.update(protocol_sha256=ph,origin='adopted_unchanged_calibration_generation',source_protocol_sha256=value['protocol_sha256'],
                     adopted_from=item['source'],adopted_sha256=item['source_sha256'])
        new(out/'generation'/task['model']/tid/'result.json',value)
        for j in JUDGES:
            source=item['judge_sources'][j];score=read(WORK/source['path'])
            score.update(protocol_sha256=ph,source_protocol_sha256=score['protocol_sha256'],origin_protocol_adoption='unchanged_calibration',adopted_from=source['path'],adopted_sha256=source['sha256'])
            new(out/'open'/tid/j/'result.json',score)
    return dict(protocol_sha256=ph,frozen=True,adopted=60,new_generation_tasks=51240,acceptance_cancelled=True)


def verify(role='maintenance',resources=True):
    ph,p,root,out=active()
    from runner import environment
    require(environment()==p['environment'],'Environment drift')
    require(source_bindings()==p['implementation'],'Formal implementation drift')
    for name,h in p['implementation'].items():require(digest(root/'implementation'/name)==h,'Frozen source drift')
    for name,h in p['public_questions'].items():require(digest(WORK/name)==h,'Public question drift')
    require(digest(EXPERIMENT/'data/resources/manifest.json')==p['resources_manifest_sha256'],'Resource manifest drift')
    if resources:
        for name,h in read(EXPERIMENT/'data/resources/manifest.json')['files'].items():require(digest(EXPERIMENT/'data/resources'/name)==h,'Resource drift: '+name)
    if role!='generation':
        for name,h in p['scoring_inputs'].items():require(digest(WORK/name)==digest(root/'inputs'/name)==h,'Scoring/human input drift')
        for item in p['adoptions']:
            require(digest(WORK/item['source'])==item['source_sha256'],'Adopted answer changed')
            for x in item['judge_sources'].values():require(digest(WORK/x['path'])==x['sha256'],'Adopted judge result changed')
    require(digest(WORK/p['design']['path'])==p['design']['sha256'],'Design drift')
    rows=read(root/'tasks.json');require(sha(encoded(rows))==p['tasks_sha256'] and len(rows)==51300,'Task matrix drift')
    return ph,p,root,out


def authorized(role):
    ph,p,root,out=verify(role,resources=False);a=read(AUTH)
    require(a['protocol_sha256']==ph and a['authorized'] and role in a['allowed_roles'],'Formal dispatch closed')
    receipt=read(root/'preflight.json');require(receipt['passed'] and receipt['protocol_sha256']==ph,'Formal preflight required')
    return ph,p,root,out


def task_generation(task,question,deployment,counter,folder,ph,*,client_factory=None,engine=None):
    """New client per task: three attempts do not poison unrelated queued tasks."""
    from runtime import run_question,tools_for
    folder=storage_path(folder);folder.mkdir(parents=True,exist_ok=True);target=folder/'result.json'
    with request_lock(target):
        if target.exists():
            value=read(target);require(value['task']==task and value['protocol_sha256']==ph,'Terminal result binding mismatch');return value
        claim=folder/'claim.json';binding=dict(task=task,protocol_sha256=ph)
        if claim.exists():
            prior=read(claim);require(all(prior[k]==v for k,v in binding.items()),'Interrupted claim binding differs')
        else:new(claim,dict(**binding,claimed_utc=now()))
        client=client_factory() if client_factory else RetryingClient(deployment,RetryPolicy(),concurrency=1)
        tools=tools_for(task['method'],task['mode'],task['budget'])
        started=time.monotonic()
        value=(engine or run_question)(question,task['mode'],task['method'],task['budget'],tools,client,deployment,counter,folder/'requests')
        if value['status']=='http_rejected':
            requests=sorted((folder/'requests').glob('*.json'))
            code=read(requests[-1]).get('http_status') if requests else None
            value['http_status']=code
            if code not in {408,429}:value['status']='service_configuration_error'
        value=dict(**binding,**value,ended_utc=now(),elapsed_seconds=time.monotonic()-started,origin='formal_generation')
        new(target,value);return value


def generation_worker(model):
    ph,p,root,out=authorized('generation')
    from runner import model_lock
    from tokenization import ChatCounter
    d=load_model(model);require(public_deployment(d)==p['models'][model],'Generation deployment drift')
    counter=ChatCounter(model);require(counter.public()==p['tokenizers'][model],'Tokenizer drift')
    rows=[r for r in read(root/'tasks.json') if r['model']==model]
    questions={part:{q['id']:q for q in read(DATA/part/'model/questions.json')} for part in ('open','objective')}
    rows.sort(key=lambda r:sha(('20261103'+r['task_id']).encode()))
    import runtime
    from chapter2_knowledge_input_guard import install
    folder=out/'generation'/model;folder.mkdir(parents=True,exist_ok=True)
    with model_lock('formal_'+model,EXPERIMENT/'runtime_locks'):
        guard=install(public_question_files=[DATA/part/'model/questions.json' for part in ('open','objective')])
        if not (folder/'input_guard.json').exists():new(folder/'input_guard.json',guard)
        done={f.parent.name for f in storage_path(folder).glob('*/result.json')}
        pending_rows=[r for r in rows if r['task_id'] not in done];counts=Counter(read(folder/t/'result.json')['status'] for t in done)
        fatal=threading.Event();poolsize=p['generation']['concurrency'][model]
        def work(task):
            try:
                value=task_generation(task,questions[task['part']][task['id']],d,counter,folder/task['task_id'],ph)
                if value['status'] in FATAL:fatal.set()
                return task['task_id'],value['status']
            except Exception as exc:
                fatal.set();state(folder/'fatal.json',dict(error_type=type(exc).__name__,task_id=task['task_id'],at=now()));raise
        with ThreadPoolExecutor(max_workers=poolsize) as pool:
            iterator=iter(pending_rows);pending=set()
            while True:
                while len(pending)<poolsize and not fatal.is_set():
                    task=next(iterator,None)
                    if task is None:break
                    pending.add(pool.submit(work,task))
                state(folder/'progress.json',dict(model=model,protocol_sha256=ph,total=len(rows),completed=sum(counts.values()),statuses=dict(counts),in_flight=len(pending),concurrency=poolsize,updated_utc=now(),fatal=fatal.is_set()))
                if not pending:break
                f=next(as_completed(pending));pending.remove(f)
                try:
                    tid,status=f.result();counts[status]+=1
                    with (folder/'events.jsonl').open('a',encoding='utf-8') as event:event.write(json.dumps(dict(task_id=tid,status=status))+'\n')
                    print(json.dumps(dict(model=model,task_id=tid,status=status,completed=sum(counts.values()))),flush=True)
                except Exception:pass
        if fatal.is_set():
            if not (folder/'fatal.json').exists():state(folder/'fatal.json',dict(reason='fatal_protocol_or_storage_status',at=now()))
            raise RuntimeError('Generation stopped on a protocol/storage error')
        state(folder/'complete.json',dict(protocol_sha256=ph,tasks=len(rows),statuses=dict(counts),completed_utc=now()))


def base_packets():
    gold={x['id']:x for x in read(DATA/'open/scoring/annotations.json')};evidence=read(DATA/'open/scoring/evidence.json')
    questions={q['id']:q for q in read(DATA/'open/model/questions.json')}
    result={}
    for qid,a in gold.items():
        result[qid]=dict(schema_version='ch2_five_level_dual_eas',question=questions[qid]['question'],conditional=a['labels']['condition_discrimination'],
                         criteria=[dict(criterion_id=x['id'],claim=x['claim'],evidence_ids=x['evidence_ids']) for x in a['required_points']],
                         sources=[dict(evidence_id=eid,**evidence[eid]) for eid in a['required_evidence_ids']],
                         applicability=a['applicability'],acceptable_answer_range=a['acceptable_answer_range'],critical_errors=a['critical_errors'])
    return result


def empty_metrics(packet):
    from judge_contract import calculate
    return calculate([None]*len(packet['criteria']),None,None if packet['conditional'] else 'not_applicable',packet['conditional'])


def judge_one(ph,task,result,packet,judge,profile,folder,*,client_factory=None):
    from judge_calibration import prompt_text,load_deployment,failure_record
    from judge_api_adapter import build,parse
    from judge_contract import schema,joint_metrics
    target=storage_path(folder/'result.json');target.parent.mkdir(parents=True,exist_ok=True)
    with request_lock(target):
        if target.exists():return read(target)
        if result['status'] in UNKNOWN:
            value=dict(status='generation_unknown',metrics=empty_metrics(packet))
        elif result['status']!='answered':
            record=failure_record(packet,judge,profile['prompt_version']);value=dict(status='complete',origin='deterministic_generation_failure',record=record,metrics=joint_metrics(record,[c['criterion_id'] for c in packet['criteria']],packet['conditional'],True))
        else:
            req=build(profile,packet,'joint',prompt_text(),schema())
            require(len(json.dumps(req['body'],ensure_ascii=False).encode())+256<=profile['input_token_cap'],'Judge input reservation exceeded')
            client=client_factory() if client_factory else RetryingClient(load_deployment(judge,profile,1),RetryPolicy(),concurrency=1)
            raw=client.complete(req['body'],folder/'requests/000.json')
            if raw['status']=='response':
                try:
                    parsed=parse(profile,raw['raw_response'],packet,'joint');value=dict(status='complete',origin='AI_judge',**parsed,metrics=joint_metrics(parsed['record'],[c['criterion_id'] for c in packet['criteria']],packet['conditional']))
                except (ValueError,KeyError,TypeError) as exc:value=dict(status='judge_output_failure',error_type=type(exc).__name__,error=str(exc),metrics=empty_metrics(packet),content_retried=False)
            elif raw['status'] in {'model_identity_mismatch','runner_error','response_persistence_error','invalid_response'} or (raw['status']=='http_rejected' and raw.get('http_status') not in {408,429}):
                raise ValueError('Judge identity or persistence failure')
            else:value=dict(status='technical_unresolved',transport_status=raw['status'],retry_exhausted=raw.get('retry_exhausted'),metrics=empty_metrics(packet))
        value.update(protocol_sha256=ph,sample_id=packet['sample_id'],judge_id=judge,answer_result_sha256=sha(encoded(result)),completed_utc=now())
        new(target,value);return value


def score_worker():
    ph,p,root,out=authorized('scoring')
    from judge_calibration import public_profile,mean_metrics
    from objective_scoring import score as objective_score
    rows={r['task_id']:r for r in read(root/'tasks.json')};bases=base_packets()
    objective_questions={q['id']:q for q in read(DATA/'objective/model/questions.json')};objective_gold={a['id']:a for a in read(DATA/'objective/scoring/annotations.json')}
    profiles={j:judge_profile(j) for j in JUDGES}
    for j in JUDGES:require(public_profile(profiles[j])==p['judging']['profiles'][j],'Judge profile drift')
    adoption={r['task']['task_id']:r['sample_id'] for r in p['adoptions']}
    ready=set();offsets={m:0 for m in MODELS};queued={j:set() for j in JUDGES};pending={j:{} for j in JUDGES}
    pools={j:ThreadPoolExecutor(max_workers=p['judging']['concurrency'][j]) for j in JUDGES}
    # Reconcile terminal results, including a crash between result persistence and event append.
    for m in MODELS:ready.update(f.parent.name for f in storage_path(out/'generation'/m).glob('*/result.json'))
    try:
        while True:
            for m in MODELS:
                events=out/'generation'/m/'events.jsonl'
                if events.exists():
                    with events.open(encoding='utf-8') as stream:
                        stream.seek(offsets[m])
                        while True:
                            before=stream.tell();line=stream.readline()
                            if not line:break
                            if not line.endswith('\n'):stream.seek(before);break
                            ready.add(json.loads(line)['task_id'])
                        offsets[m]=stream.tell()
            for j in JUDGES:
                for f,tid in list(pending[j].items()):
                    if f.done():f.result();del pending[j][f]
            for tid in sorted(ready):
                task=rows[tid];source=out/'generation'/task['model']/tid/'result.json'
                if task['part']=='objective':
                    dest=out/'objective'/tid/'result.json'
                    if not storage_path(dest).exists():new(dest,dict(protocol_sha256=ph,task=task,answer_result_sha256=digest(source),**objective_score(objective_questions[task['id']],objective_gold[task['id']],read(source))))
                    continue
                r=None;packet=None
                for j in JUDGES:
                    dest=out/'open'/tid/j/'result.json'
                    if storage_path(dest).exists() or tid in queued[j] or len(pending[j])>=p['judging']['concurrency'][j]*2:continue
                    if r is None:
                        r=read(source);packet=dict(bases[task['id']],sample_id=adoption.get(tid,'F-'+tid[:20]),answer=r.get('answer') if r['status']=='answered' else '[未生成有效回答：'+r['status']+']',generation_failed=r['status'] not in UNKNOWN and r['status']!='answered')
                    queued[j].add(tid);pending[j][pools[j].submit(judge_one,ph,task,r,packet,j,profiles[j],dest.parent)]=tid
                pair=[out/'open'/tid/j/'result.json' for j in JUDGES];dest=out/'open'/tid/'mean.json'
                if not storage_path(dest).exists() and all(storage_path(x).exists() for x in pair):
                    q=bases[task['id']];values=[read(x) for x in pair];metrics=[v.get('metrics') or empty_metrics(q) for v in values]
                    new(dest,dict(protocol_sha256=ph,task=task,judges={j:dict(status=v['status'],result_sha256=digest(x)) for j,v,x in zip(JUDGES,values,pair)},metrics=mean_metrics(*metrics)))
            complete=all((out/'generation'/m/'complete.json').exists() for m in MODELS)
            objective_count=sum(1 for tid in ready if rows[tid]['part']=='objective' and storage_path(out/'objective'/tid/'result.json').exists())
            open_count=sum(1 for tid in ready if rows[tid]['part']=='open' and storage_path(out/'open'/tid/'mean.json').exists())
            state(out/'scoring_progress.json',dict(protocol_sha256=ph,objective_completed=objective_count,objective_total=34200,open_completed=open_count,open_total=17100,pending={j:len(pending[j]) for j in JUDGES},updated_utc=now()))
            if complete and objective_count==34200 and open_count==17100:
                state(out/'scoring_complete.json',dict(protocol_sha256=ph,completed_utc=now()));return
            time.sleep(10)
    finally:
        for pool in pools.values():pool.shutdown(wait=True)


def supervise():
    ph,p,root,out=authorized('generation')
    require(read(AUTH)['authorized'],'Dispatch closed');logs=out/'logs';logs.mkdir(exist_ok=True)
    from runner import model_lock
    with model_lock('formal_supervisor',EXPERIMENT/'runtime_locks'):
        roles=[('generation',m) for m in MODELS]+[('scoring',None)];children={};restarts=Counter()
        while True:
            statuses={}
            for role,model in roles:
                name=model or 'scoring';complete=(out/'generation'/model/'complete.json') if model else out/'scoring_complete.json'
                fatal=(out/'generation'/model/'fatal.json') if model else out/'scoring_fatal.json'
                if complete.exists():statuses[name]=dict(status='complete');continue
                if fatal.exists():statuses[name]=dict(status='fatal_requires_reconciliation');continue
                proc=children.get(name)
                if proc is None or proc.poll() is not None:
                    if proc is not None:restarts[name]+=1
                    command=[sys.executable,'-X','utf8',str(HERE/'formal_experiment.py'), 'generation' if model else 'scoring']+(['--model',model] if model else [])
                    with (logs/f'{name}.log').open('a',encoding='utf-8') as log:
                        proc=subprocess.Popen(command,cwd=WORK,stdout=log,stderr=log,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                    children[name]=proc
                statuses[name]=dict(status='running',pid=proc.pid,restarts=restarts[name])
            state(out/'supervisor.json',dict(protocol_sha256=ph,pid=os.getpid(),updated_utc=now(),workers=statuses))
            if all(v['status']=='complete' for v in statuses.values()):return
            time.sleep(10)


def status():
    ph,p,root,out=active();result=dict(protocol_sha256=ph,output_root=relative(out),acceptance_cancelled=True)
    for m in MODELS:
        path=out/'generation'/m/'progress.json';result[m]=read(path) if path.exists() else dict(status='not_started')
    for name in ('scoring_progress','supervisor'):
        path=out/(name+'.json')
        if path.exists():result[name]=read(path)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=['freeze','verify','generation','scoring','supervise','status']);parser.add_argument('--model',choices=MODELS);args=parser.parse_args()
    if args.command=='freeze':result=freeze()
    elif args.command=='verify':
        ph,p,root,out=verify();result=dict(passed=True,protocol_sha256=ph,task_count=p['task_count'],acceptance_cancelled=True)
    elif args.command=='status':result=status()
    elif args.command=='generation':generation_worker(args.model);result=dict(model=args.model,completed=True)
    elif args.command=='scoring':
        try:score_worker();result=dict(scoring_complete=True)
        except Exception as exc:
            _,_,_,out=active();state(out/'scoring_fatal.json',dict(error_type=type(exc).__name__,at=now()));raise
    else:supervise();result=dict(completed=True)
    print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
