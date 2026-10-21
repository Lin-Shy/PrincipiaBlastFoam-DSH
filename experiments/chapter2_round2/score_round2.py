"""Independent, immutable score-side execution of the existing calibrated rubric.

Freeze before any paid judging. Each completed generation arm is audited and its
payloads are sealed before any request for that arm. No unfinished answers read.
"""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import hashlib
import random
import threading
import time

from common import *

CONFIG = ARCHIVE/'configs/scoring_14b_v1.json'

def now(): return datetime.now(timezone.utc).isoformat()

def update(path, value):
    temp=path.with_suffix('.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    temp.replace(path)

def freeze():
    generation=ARCHIVE/'configs/e2e_14b_v1.json';g=read(generation)
    old=read(HISTORICAL/'protocol.json')
    calibration=Path(g['judge']['calibration'])
    if sha(calibration/'completion.json')!=g['judge']['calibration_completion_sha256'] or not read(calibration/'completion.json')['calibration_passed']:
        raise ValueError('bound original calibration not passed')
    implementation=dict(g['legacy_code'])
    for name in ['chapter2_formal_scoring_200.py','chapter2_model14b_analysis_200.py']:
        path=LEGACY/name;implementation[path.relative_to(PROJECT).as_posix()]=sha(path)
    for name,digest in g['legacy_code'].items():
        if sha(PROJECT/name)!=digest:raise ValueError('original scorer implementation drift')
    for name,digest in g['scoring_data_sha256'].items():
        if sha(DATASET/'scoring'/name)!=digest:raise ValueError('original scoring data drift')
    p=dict(schema='round2_calibrated_scoring_v1',frozen_utc=now(),generation_protocol_sha256=sha(generation),
        arms=g['arms'],questions=200,sessions=1400,model='qwen3-14b',provider='qwen_proxy',workload='bulk',
        endpoint=g['endpoint'],temperature=0,enable_thinking=False,workers=4,
        combined_endpoint_concurrency='At most4 judge workers plus existing1 generation worker, below shared16 cap',
        input_tokens_per_request=32768,output_tokens_per_request=4096,max_transport_attempts=1,
        content_retries=0,targeted_reviews_per_answer=0,seed=20261020,
        judge=g['judge'],statistics=g['statistics'],scoring_data_sha256=g['scoring_data_sha256'],
        questions_sha256=g['questions_sha256'],source_map_sha256=g['source_map_sha256'],
        tokenizer_binding_sha256=g['tokenizer_binding_sha256'],implementation_sha256=implementation,
        generation_code=g['code'],driver_sha256=sha(Path(__file__)),analysis_sha256=sha(HERE/'analyze_e2e.py'),
        annotation_policy='Existing200 scoring data unchanged. Independent scoring process only.',
        anonymity='Question, anonymous actual answer, required points and original sources only; never arm/id/model in request payload',
        over_limit='Do not trim or export; answer is judge_unknown with[0,1] bounds',
        failure='Generation failure0; unknown judged answers retain bounds; all200 per arm',
        batch_policy='Only read an arm after completed.json; audit all200 and seal payload hashes before judging. Each request sent once; never auto-replay.',
        infrastructure_stop='Stop dispatch after401/402/403/429, identity/budget violation, or3 consecutive transport failures per worker. Inflight workers finish and save outcomes.',
        holdout='Not included. New60 require actual question-level human review, overlap audit and separate data freeze.')
    save(CONFIG,p)
    runtime=ARCHIVE/'scoring_runtime_v1';runtime.mkdir(exist_ok=False)
    for name in ['score_round2.py','analyze_e2e.py']:(runtime/name).write_bytes((HERE/name).read_bytes())
    approval=ARCHIVE/'authorizations/scoring14b_001.json'
    save(approval,dict(approved=True,scope='scoring',protocol_sha256=sha(CONFIG),max_sessions=1400,
        user_instruction='继续，完成付费评分，完成新留出集验证，确认',recorded_utc=now(),
        price='Actual private proxy prices/balance/quotas unknown; token projections previously disclosed',
        holdout_execution_approved=True,holdout_human_question_review_completed=False))
    print(json.dumps(dict(frozen=True,protocol_sha256=sha(CONFIG),approval=str(approval))))

def verify(approval):
    p=read(CONFIG);a=read(approval)
    if not a.get('approved') or a.get('scope')!='scoring' or a.get('protocol_sha256')!=sha(CONFIG) or a.get('max_sessions',0)<p['sessions']:
        raise PermissionError('exact scoring approval required')
    if sha(Path(__file__))!=p['driver_sha256'] or sha(HERE/'analyze_e2e.py')!=p['analysis_sha256']:
        raise ValueError('scoring/analysis source drift')
    for n,h in p['implementation_sha256'].items():
        if sha(PROJECT/n)!=h:raise ValueError('calibrated source drift: '+n)
    for n,h in p['generation_code'].items():
        if sha(HERE/n)!=h:raise ValueError('generation source drift: '+n)
    for n,h in p['scoring_data_sha256'].items():
        if sha(DATASET/'scoring'/n)!=h:raise ValueError('annotation drift')
    if sha(QUESTIONS)!=p['questions_sha256'] or sha(RESOURCES/'source-map.json')!=p['source_map_sha256']:
        raise ValueError('question/corpus manifest drift')
    if sha(ARCHIVE/'configs/e2e_14b_v1.json')!=p['generation_protocol_sha256']:raise ValueError('generation protocol drift')
    calibration=Path(p['judge']['calibration'])
    if sha(calibration/'completion.json')!=p['judge']['calibration_completion_sha256']:raise ValueError('calibration drift')
    from chapter2_qwen_proxy_config import settings
    base,key=settings(WORKSPACE/'.env.qwen_proxy');del key
    if base+'/chat/completions'!=p['endpoint']:raise ValueError('endpoint drift')
    return p

def audit_generation(folder, question, arm, g, cache):
    from chapter2_common_qa_interface import neutral_messages
    from chapter2_qa_deployment import prepared_messages, ANSWER_CHECKLIST
    r=read(folder/'result.json');mb=g['model_budget'];kb=g['knowledge_budget']
    if r['arm']!=arm or r['id']!=folder.name or r['protocol_sha256']!=sha(ARCHIVE/'configs/e2e_14b_v1.json'):
        raise ValueError('generation binding drift')
    if len(r['tool_events'])>kb['tool_calls'] or r['knowledge_characters']>kb['total_characters']:
        raise ValueError('tool budget violated')
    if r['counted_input_tokens']>mb['input_tokens_total'] or r['actual_completion_tokens']>mb['output_tokens_total']:
        raise ValueError('model budget violated')
    source_hashes=read(RESOURCES/'source-map.json')['files'];ledger=set()
    for event in r['tool_events']:
        response=event['response'];size=event['delivered_characters'];delivered=set()
        if len(response)!=size or size>kb['tool_characters']:raise ValueError('serialized tool budget drift')
        for block in (json.loads(response) if response else {}).get('evidence',[]):
            path=block['path']
            if path not in source_hashes:raise ValueError('outside corpus')
            if path not in cache:
                raw=(RESOURCES/'corpus'/path).read_bytes()
                cache[path]=(hashlib.sha256(raw).hexdigest(),raw.decode('utf-8').splitlines())
            digest,lines=cache[path]
            if digest!=block['sha256'] or digest!=source_hashes[path]:raise ValueError('source digest drift')
            if [line['number'] for line in block['lines']]!=list(range(block['start'],block['end']+1)):
                raise ValueError('source coordinates drift')
            for line in block['lines']:
                if lines[line['number']-1]!=line['text']:raise ValueError('source text drift')
                delivered.add((path,line['number']))
        if delivered!={(x['path'],x['line']) for x in event['delivered_original_lines']}:raise ValueError('event ledger drift')
        ledger|=delivered
    if ledger!={(x['path'],x['line']) for x in r['delivered_lines']}:raise ValueError('delivery ledger drift')
    if sum(e['delivered_characters'] for e in r['tool_events'])!=r['knowledge_characters']:raise ValueError('character accounting drift')
    records=sorted((folder/'requests').glob('*.json'))
    if len(records)!=len(r['turns']) or len(records)>kb['tool_calls']+1:raise ValueError('turn accounting drift')
    for i,(path,turn) in enumerate(zip(records,r['turns'])):
        record=read(path);body=record['request']
        expected={**turn['request'],'messages':neutral_messages(prepared_messages(turn['request']['messages'],ANSWER_CHECKLIST))}
        fingerprint=hashlib.sha256(json.dumps(body,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        if body!=expected or record['request_sha256']!=fingerprint or path.stem!=f'{i:02d}':raise ValueError('request/prompt identity drift')
        if record['provider']!='qwen_proxy' or record['model']!='qwen3-14b' or record['endpoint']!=g['endpoint']:
            raise ValueError('generation deployment drift')
        if record['transport_attempts']!=1 or record['content_retries']!=0 or record['status']=='in_flight':raise ValueError('request unresolved/replayed')
        if record['status']=='response' and record.get('response',{}).get('model')!='qwen3-14b':raise ValueError('provider model changed')
        if i==0 and body['messages'][1]['content']!=question:raise ValueError('question changed')
        if body['max_tokens']>mb['output_tokens_per_request'] or turn['counted_input_tokens']>mb['input_tokens_per_request']:
            raise ValueError('request token budget drift')
    if r['status']=='answered':
        valid=all(isinstance(ref,dict) and set(ref)=={'path','start','end'}
            and type(ref['start'])is int and type(ref['end'])is int and 1<=ref['start']<=ref['end']
            and all((ref['path'],n)in ledger for n in range(ref['start'],ref['end']+1))for ref in r['references'])
        if valid!=r['references_delivered']:raise ValueError('reference delivery flag drift')
    return dict(id=r['id'],result_sha256=sha(folder/'result.json'),request_sha256={path.name:sha(path) for path in records},passed=True)

def seal_arm(generation_root,out,arm,p):
    from chapter2_autonomous_qa import load_tokenizer
    from chapter2_answer_scoring import scoring_payload
    from chapter2_judge_200_rubric import requests
    from principia_core.retrieval.knowledge_qa import FrozenKnowledgeCorpus
    completed=read(generation_root/arm/'completed.json');g=read(ARCHIVE/'configs/e2e_14b_v1.json')
    qs=public_questions();anns={a['id']:a for a in read(DATASET/'scoring/annotations.json')}
    evidence=read(DATASET/'scoring/evidence.json');corpus=FrozenKnowledgeCorpus(RESOURCES/'corpus',RESOURCES/'corpus-manifest.json')
    counter,_=load_tokenizer(RESOURCES/'tokenizers/qwen3-14b','qwen3-14b')
    if completed['questions']!=200 or set(completed['results_sha256'])!={q['id'] for q in qs}:raise ValueError('incomplete arm')
    rows=[];audits=[];cache={}
    for q in qs:
        folder=generation_root/arm/'generation'/q['id'];source=folder/'result.json'
        if sha(source)!=completed['results_sha256'][q['id']]:raise ValueError('completed answer drift')
        audits.append(audit_generation(folder,q['question'],arm,g,cache));r=read(source)
        row=dict(arm=arm,id=q['id'],generation_sha256=sha(source),generation_status=r['status'])
        if r['status']=='answered':
            payload=scoring_payload(q['question'],anns[q['id']],evidence,corpus,r['answer'],r['delivered_lines'])
            path=out/'payloads'/arm/(q['id']+'.json');save(path,payload)
            row.update(payload_sha256=sha(path),input_tokens=[counter(v['body']['messages']) for v in requests(payload)])
        rows.append(row)
    random.Random(p['seed']).shuffle(rows)
    value=dict(arm=arm,rows=rows,generation_completion_sha256=sha(generation_root/arm/'completed.json'),
        scoring_protocol_sha256=sha(CONFIG),generation_audits=audits,
        requests=sum(len(r.get('input_tokens',[])) for r in rows if max(r.get('input_tokens',[0]))<=32768),
        input_limit_answers=sum(max(r.get('input_tokens',[0]))>32768 for r in rows),sealed_utc=now())
    save(out/'sealed_arms'/(arm+'.json'),value)
    return value

def score_arm(generation_root,out,arm,p,sealed):
    from chapter2_formal_scoring_200 import failed_generation,unidentified
    from chapter2_judge_200_rubric import requests,parse
    from chapter2_judge_200 import call_once
    from chapter2_qwen_routing import routed_client
    stop=threading.Event();reasons=[];local=threading.local()
    def one(row):
        if stop.is_set():return None
        folder=out/'sessions'/arm/row['id'];source=generation_root/arm/'generation'/row['id']/'result.json'
        if sha(source)!=row['generation_sha256']:raise ValueError('sealed answer drift')
        infra=None
        if row['generation_status']!='answered':result=failed_generation(row['generation_status'])
        elif max(row['input_tokens'])>p['input_tokens_per_request']:result=unidentified('judge_input_budget_exceeded_before_export')
        else:
            path=out/'payloads'/arm/(row['id']+'.json')
            if sha(path)!=row['payload_sha256']:raise ValueError('sealed payload drift')
            payload=read(path);client=routed_client('qwen3-14b',folder/'requests',workload='bulk',timeout=180)
            records=[]
            for i,req in enumerate(requests(payload)):
                if stop.is_set():break
                record=call_once(client,req['body'],i);records.append(record)
                local.streak=getattr(local,'streak',0)+1 if record['status'] in {'transport_error','http_rejected','invalid_response'} else 0
                if record.get('http_status') in {401,402,403,429} or record['status']=='model_mismatch':infra='provider_auth_quota_rate_or_identity'
                if record.get('response',{}).get('usage',{}).get('completion_tokens',0)>4096:infra='provider_output_budget_violation'
                if local.streak>=3:infra='three_consecutive_transport_failures'
                if infra:reasons.append(dict(arm=arm,id=row['id'],reason=infra));stop.set();break
            result=parse(records,payload) if len(records)==len(requests(payload)) else unidentified('infrastructure_stopped_before_all_judge_stages')
            if 'metrics' not in result:result={**unidentified(result.get('reason','unparseable')),**result}
        result.update(arm=arm,id=row['id'],generation_sha256=row['generation_sha256'],execution_protocol_sha256=sha(CONFIG))
        save(folder/'result.json',result)
        return result
    results=[]
    with ThreadPoolExecutor(max_workers=p['workers']) as pool:
        futures=[pool.submit(one,row) for row in sealed['rows']]
        for future in as_completed(futures):
            result=future.result()
            if result is not None:results.append(result)
            if len(results)%10==0:
                update(out/'live_status.json',dict(status='scoring',active_arm=arm,arm_completed=len(results),
                    total_completed=len(list((out/'sessions').glob('*/*/result.json'))),planned=1400,
                    statuses=dict(Counter(r['status'] for r in results)),updated_utc=now(),holdout_started=False))
    if stop.is_set():
        save(out/'infrastructure_stop.json',dict(reasons=reasons,completed=len(results),no_retries=True));raise RuntimeError('judge infrastructure stop; receipts retained')
    if len(results)!=200:raise ValueError('incomplete scoring arm')
    save(out/'completed_arms'/(arm+'.json'),dict(sessions=200,statuses=dict(Counter(r['status'] for r in results)),
        sealed_arm_sha256=sha(out/'sealed_arms'/(arm+'.json')),protocol_sha256=sha(CONFIG),
        results_sha256={r['id']:sha(out/'sessions'/arm/r['id']/'result.json') for r in results}))

def run(run_id,approval):
    p=verify(approval);gen=ARCHIVE/'e2e_runs'/run_id;out=gen/'scoring_001';out.mkdir(exist_ok=False)
    save(out/'execution_manifest.json',dict(protocol_sha256=sha(CONFIG),approval_sha256=sha(approval),started_utc=now()))
    for arm in p['arms']:
        while not (gen/arm/'completed.json').exists():
            if (gen/'controller_stop.json').exists():raise RuntimeError('generation stopped; no complete arm to judge')
            update(out/'live_status.json',dict(status='waiting_for_completed_generation_arm',active_arm=arm,
                total_completed=len(list((out/'sessions').glob('*/*/result.json'))),planned=1400,updated_utc=now(),holdout_started=False))
            time.sleep(15)
        verify(approval)
        sealed=seal_arm(gen,out,arm,p);score_arm(gen,out,arm,p,sealed)
    bindings={f'{arm}/{qid}':digest for arm in p['arms'] for qid,digest in read(out/'completed_arms'/(arm+'.json'))['results_sha256'].items()}
    save(out/'completion.json',dict(sessions=1400,execution_protocol_sha256=sha(CONFIG),results_sha256=bindings,completed_utc=now()))
    update(out/'live_status.json',dict(status='scoring_complete',total_completed=1400,planned=1400,updated_utc=now(),holdout_started=False))
    from analyze_e2e import analyze
    analyze(gen,out,gen/'analysis_001')

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('action',choices=['freeze','run']);ap.add_argument('--run-id',default='answer14b_001');ap.add_argument('--approval',type=Path)
    args=ap.parse_args()
    if args.action=='freeze':freeze()
    else:
        try:run(args.run_id,args.approval)
        except Exception as error:
            out=ARCHIVE/'e2e_runs'/args.run_id/'scoring_001'
            if out.exists():update(out/'live_status.json',dict(status='stopped_error',error_type=type(error).__name__,message=str(error),updated_utc=now(),holdout_started=False))
            raise
