"""Authorized Objective200 experiment. Isolated manifests, generation and deterministic scoring."""
import argparse, csv, hashlib, json, os, subprocess, sys, threading, time, traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from pathlib import Path
from datetime import datetime, timezone

HERE=Path(__file__).resolve().parent
WORK=HERE.parents[2]
sys.path.insert(0,str(HERE.parent/'retrieval_method'))
DATA=WORK/'graduation-datasets/chapter02_knowledge_qa/objective_v1_200'
BASE=WORK/'graduation-experiment-results/chapter2_retrieval'
OUT=BASE/'objective200'
MANIFEST=OUT/'manifest.json'
LOCK=threading.RLock()
SUPERCOMPUTER_SETTINGS=WORK/'.env.supercomputer'
FORMAT='\n本题为客观题。继续遵守工具调用和final JSON协议。在最终JSON的answer字符串末尾单独一行填写 FINAL: 答案。单选只填A/B/C/D；判断只填正确或错误；填空及短答只填原始键名、配置值或数值。数值使用题目指定单位，不加单位后缀。只允许一条FINAL行，不列多个候选。'
def now():return datetime.now(timezone.utc).isoformat()
def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,obj):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    tmp=p.with_suffix(p.suffix+'.tmp');tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');os.replace(tmp,p)
def event(**obj):
    with LOCK:
        OUT.mkdir(parents=True,exist_ok=True)
        with (OUT/'events.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(dict(utc=now(),**obj),ensure_ascii=False)+'\n')
def question_text(q):
    options='\n'+'\n'.join(k+'. '+v for k,v in q['options'].items()) if q.get('options') else ''
    return q['question']+options+FORMAT

def supercomputer_deployment():
    from chapter2_qwen_local import load_model
    deployment=load_model('qwen3-8b',SUPERCOMPUTER_SETTINGS)
    return dict(endpoint=deployment.endpoint,api_model_id=deployment.model,
                max_concurrency=deployment.max_concurrency,source='supercomputer',
                protocol='chat_completions',context_limit=32768)

def supercomputer_client(folder):
    from chapter2_qwen_routing import routed_client
    recorded=routed_client('qwen3-8b',folder/'requests',settings_path=SUPERCOMPUTER_SETTINGS,timeout=600)
    def call(body,turn):
        result=recorded(body,turn)
        if result.get('status')=='model_mismatch':
            result['status']='model_identity_mismatch'
        if result.get('status')=='response':
            raw=result['raw_response']; usage=raw.get('usage',{})
            if any(type(usage.get(k)) is not int for k in ('prompt_tokens','completion_tokens')):
                return dict(status='usage_unknown',raw_response=raw)
            if usage['prompt_tokens']+usage['completion_tokens']>32768 or usage['completion_tokens']>body['max_tokens']:
                return dict(status='provider_budget_violation',raw_response=raw)
            result['response']={**raw,'model':'qwen3-8b'}
        return result
    return call

def prepare():
    if MANIFEST.exists():return verify()
    qs=read(DATA/'model/questions.json');gs=read(DATA/'scoring/annotations.json')
    dataset=read(DATA/'dataset.json')
    if dataset.get('context_review_complete') is not True:
        raise ValueError('Candidate dataset has not completed contextual review')
    if dataset.get('count')!=len(qs):raise ValueError('Dataset count does not match questions')
    assert qs and len(qs)==len(gs) and len({q['id'] for q in qs})==len(qs)
    assert {q['id'] for q in qs}=={g['id'] for g in gs}
    assert all(set(q)<= {'id','question','type','options'} for q in qs)
    for g in gs:
        for e in g['evidence']:
            p=BASE/'data/resources/corpus'/e['path']
            assert sha(p)==e['sha256']
            assert p.read_text(encoding='utf-8').splitlines()[e['start']-1]==e['text']
    old=read(BASE/'release/manifests/test160_manifest.json')
    from central_execution import Registry
    registry=Registry()
    bindings={str(p.relative_to(WORK)).replace('\\','/'):sha(p) for p in
              [DATA/'model/questions.json',DATA/'scoring/annotations.json',DATA/'dataset.json',
               HERE/'objective_scoring.py',HERE/'objective_experiment.py',HERE/'test160_runner.py',
               BASE/'data/resources/corpus-manifest.json',BASE/'release/manifests/test160_manifest.json']}
    m=dict(schema='objective200_v1',created=now(),questions=len(qs),tasks=len(qs)*26,
           question_file=str((DATA/'model/questions.json').relative_to(WORK)),
           configurations=old['configurations'],deployments={'qwen3_8b':supercomputer_deployment(),'qwen3_14b':registry.resolve('qwen3_14b')},
           bindings=bindings,format_instruction=FORMAT,authorizer='project owner',
           authorization='2026-11-02 explicit instruction to implement full experiment, paid calls and local Git commits; no financial approval gate',
           retries=2,scoring='deterministic binary; failures zero; fixed denominator',
           analysis=dict(seed=20261102,bootstrap_samples=10000,clusters='source manual chapter or tutorial case; conservative dependence grouping',
                         families={'main':16,'ablation':8},paired_test='cluster sign-flip, exact up to 20 clusters, otherwise 100000 Monte Carlo flips',
                         primary='overall accuracy',secondary='four-type macro accuracy'),
           review='AI source review, not independent human audit',knowledge_holdout=False)
    assert len(m['configurations'])==26
    save(MANIFEST,m)
    save(OUT/'authorization.json',dict(authorized=True,manifest_sha256=sha(MANIFEST),scope='26 Agentic configurations; all frozen questions; up to 2 definite-technical retries per request',user_instruction=m['authorization']))
    return m

def verify(generation=False):
    m=read(MANIFEST)
    for rel,digest in m['bindings'].items():
        if generation and '/scoring/' in rel:continue
        if sha(WORK/rel)!=digest:raise ValueError('Frozen file changed: '+rel)
    return m

def generation_guard():
    banned=[str(DATA/'scoring').lower(),str(BASE/'data/gold').lower(),str(BASE/'evaluation').lower(),str(OUT/'scores').lower()]
    def hook(name,args):
        if name=='open' and args and isinstance(args[0],(str,bytes,os.PathLike)):
            path=os.path.abspath(os.fsdecode(args[0])).lower()
            if any(path.startswith(p) for p in banned):raise PermissionError('Scoring-side read forbidden during generation')
    sys.addaudithook(hook)

def initialize_runtime(m):
    os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',TOKENIZERS_PARALLELISM='false',OMP_NUM_THREADS='2')
    import torch
    torch.set_num_threads(2)
    import test160_runner as runner
    tools,engine,corpus=runner.runtime(m)
    from transformers import AutoTokenizer
    tokenizer=AutoTokenizer.from_pretrained(str(BASE/'data/resources/tokenizers/qwen3-14b'),local_files_only=True,trust_remote_code=False)
    return tools,engine,tokenizer

def check():
    m=verify();generation_guard()
    tools,engine,tokenizer=initialize_runtime(m)
    rows=[]
    # Non-test example, only to verify tools and embeddings are available.
    for c in m['configurations']:
        session=tools(c,None)
        if c['method_id'] not in ('basic','direct'):
            response=session.execute('search',{'query':'blastFoam documentation'})
            if not session.events or session.events[-1]['status']!='returned':raise RuntimeError((c['config_id'],session.events))
        rows.append(c['config_id'])
    save(OUT/'preflight.json',dict(status='passed',configurations=rows,model_requests=0,checked=now()))
    print('Offline preflight passed:',len(rows),flush=True)

def run(model=None,limit=None,workers=None):
    m=verify(generation=True);qs=read(WORK/m['question_file']);generation_guard()
    from central_execution import Registry,exclusive_lock
    import dev40_supplement as transport
    transport.ROOT=OUT
    import test160_live
    test160_live.extend_local_timeout()
    make_tools,engine,tokenizer=initialize_runtime(m)
    from principia_core.retrieval.knowledge_agent import AutonomousKnowledgeAgent,ModelBudget
    from chapter2_common_qa_interface import neutral_messages
    from chapter2_qa_deployment import prepared_messages,ANSWER_CHECKLIST
    registry=Registry()
    for key,route in m['deployments'].items():
        current=supercomputer_deployment() if key=='qwen3_8b' else registry.resolve(key)
        if current!=route:raise ValueError('Deployment drift '+key)
    def count(messages):
        with LOCK:return len(tokenizer.apply_chat_template(messages,tokenize=True,add_generation_prompt=True,enable_thinking=False))
    stop={}
    def job(c,q):
        folder=OUT/'generation'/c['config_id']/q['id'];path=folder/'result.json'
        if path.exists():return
        if stop.get(c['model_key']):return
        if (folder/'requests').exists():
            event(kind='unknown_hold',config=c['config_id'],question=q['id']);return
        folder.mkdir(parents=True,exist_ok=True)
        start=time.monotonic();route=m['deployments'][c['model_key']]
        session=make_tools(c,folder)
        def transform(messages):
            transformed=prepared_messages(messages,ANSWER_CHECKLIST)
            if c['method_id']!='basic':transformed=neutral_messages(transformed)
            if route.get('append_last_user_suffix'):
                for msg in reversed(transformed):
                    if msg['role']=='user':msg['content']+='\n'+route['append_last_user_suffix'];break
            return transformed
        raw_client=supercomputer_client(folder) if c['model_key']=='qwen3_8b' else transport.client(folder,c['logical_model'])
        def client(body,turn):
            payload=deepcopy(body);payload['messages']=transform(body['messages'])
            if count(payload['messages'])+payload['max_tokens']>32768:return dict(status='combined_context_budget_exhausted')
            response=raw_client(payload,turn)
            for attempt,delay in enumerate((5,20),1):
                if response.get('http_status') not in (429,500,502,503,504):break
                time.sleep(delay);retry=folder/'retries'/f'{turn}_{attempt}';retry.mkdir(parents=True,exist_ok=False)
                response=(supercomputer_client(retry) if c['model_key']=='qwen3_8b' else transport.client(retry,c['logical_model']))(payload,turn)
            if response['status'] in ('model_identity_mismatch','provider_budget_violation','usage_unknown'):
                stop[c['model_key']]=response['status'];event(kind='branch_stopped',model=c['model_key'],reason=response['status'])
            return response
        try:
            result=AutonomousKnowledgeAgent(c['logical_model'],session,client,lambda z:count(transform(z)),ModelBudget(input_tokens_per_request=30720)).run(question_text(q))
        except Exception as exc:
            # Infrastructure exception is visible and not silently presented as a model answer.
            event(kind='infrastructure_error',config=c['config_id'],question=q['id'],error_type=type(exc).__name__)
            stop[c['model_key']]=type(exc).__name__
            raise
        result.update(id=q['id'],config_id=c['config_id'],arm=c['method_id'],manifest_sha256=sha(MANIFEST),
                      elapsed_seconds=time.monotonic()-start,completed=now(),delivered_lines=[dict(path=p,line=n) for p,n in sorted(session.delivered_lines)])
        save(path,result)
        event(kind='terminal',config=c['config_id'],question=q['id'],status=result['status'])
    def lane(key):
        configs=[c for c in m['configurations'] if c['model_key']==key]
        jobs=[(c,q) for q in qs for c in configs if not (OUT/'generation'/c['config_id']/q['id']/'result.json').exists()]
        if limit:jobs=jobs[:limit]
        n=min(workers or (8 if key=='qwen3_8b' else 20),8 if key=='qwen3_8b' else 20)
        with exclusive_lock(OUT/('run_'+key+'.lock')):
            with ThreadPoolExecutor(max_workers=n) as pool:
                futures=[pool.submit(job,*j) for j in jobs]
                for i,f in enumerate(as_completed(futures),1):
                    f.result()
                    if i%20==0:print(key,i,'/',len(jobs),flush=True)
    keys=[model] if model else ['qwen3_8b','qwen3_14b']
    with ThreadPoolExecutor(max_workers=len(keys)) as pool:list(pool.map(lane,keys))

def export_csv(path,rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    if not rows:return
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)

def report():
    from objective_scoring import score
    m=verify();qs=read(DATA/'model/questions.json');gold={g['id']:g for g in read(DATA/'scoring/annotations.json')}
    rows=[];summaries=[]
    for c in m['configurations']:
        subset=[]
        for q in qs:
            p=OUT/'generation'/c['config_id']/q['id']/'result.json'
            result=read(p) if p.exists() else None
            detail=score(q,gold[q['id']],result) if result else dict(id=q['id'],type=q['type'],raw_answer='',normalized_answer='',score=None,format_valid=None,reason='pending',scoring_version='objective_rules_v1')
            detail.update(config_id=c['config_id'],model=c['logical_model'],method=c['method_id'],cluster=gold[q['id']]['fact_cluster'],capability=gold[q['id']]['capability'],
                          question=question_text(q).split(FORMAT)[0],expected=gold[q['id']]['answer'],generation_status=result['status'] if result else 'pending',
                          seconds=result.get('elapsed_seconds',0) if result else 0,
                          tools=len(result.get('tool_events',[])) if result else 0,
                          prompt_tokens=sum(t.get('response',{}).get('raw_response',{}).get('usage',{}).get('prompt_tokens',0) for t in result.get('turns',[])) if result else 0,
                          completion_tokens=result.get('actual_completion_tokens',0) if result else 0,
                          evidence=json.dumps(gold[q['id']]['evidence'],ensure_ascii=False))
            rows.append(detail);subset.append(detail)
        complete=all(r['score'] is not None for r in subset)
        sums=dict(config_id=c['config_id'],model=c['logical_model'],method=c['method_id'],planned=len(qs),completed=sum(r['score'] is not None for r in subset),
                  answered=sum(r['generation_status']=='answered' for r in subset),correct=sum(r['score'] or 0 for r in subset),
                  accuracy=sum(r['score'] or 0 for r in subset)/len(qs) if complete else None,
                  format_valid=sum(r['format_valid'] is True for r in subset),tool_adoption=sum(r['tools']>0 for r in subset),
                  prompt_tokens=sum(r['prompt_tokens'] for r in subset),completion_tokens=sum(r['completion_tokens'] for r in subset),seconds=sum(r['seconds'] for r in subset))
        for typ in ('fill','short','single','judge'):
            part=[r for r in subset if r['type']==typ]
            sums[typ+'_accuracy']=sum(r['score'] or 0 for r in part)/len(part) if complete else None
        sums['macro_accuracy']=sum(sums[t+'_accuracy'] for t in ('fill','short','single','judge'))/4 if complete else None
        summaries.append(sums)
    save(OUT/'scores/per_answer.json',rows);export_csv(OUT/'results/per_answer.csv',rows);export_csv(OUT/'results/summary.csv',summaries)
    snapshot=dict(updated=now(),manifest_sha256=sha(MANIFEST),planned=m['tasks'],completed=sum(r['score'] is not None for r in rows),
                  status='closed' if all(r['score'] is not None for r in rows) else 'in_progress',configurations=summaries)
    if snapshot['status']=='closed':
        from objective_statistics import analyze
        snapshot['statistics']=analyze(rows,m['analysis'])
    save(OUT/'results/snapshot.json',snapshot)
    from objective_report import render
    render(OUT,rows,snapshot)
    print(json.dumps({k:v for k,v in snapshot.items() if k not in ('configurations','statistics')},ensure_ascii=False),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=['prepare','check','run','report'])
    p.add_argument('--model',choices=['qwen3_8b','qwen3_14b']);p.add_argument('--limit',type=int);p.add_argument('--workers',type=int)
    a=p.parse_args()
    if a.command=='prepare':prepare()
    elif a.command=='check':check()
    elif a.command=='run':run(a.model,a.limit,a.workers)
    else:report()
