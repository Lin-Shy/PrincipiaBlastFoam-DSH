"""Authorized isolated Single-Pass RAG Dev40 run and dual scoring."""
import runtime_layout as layout
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from datetime import datetime, timezone
import csv, hashlib, http.client, json, os, ssl, statistics, sys, threading, time
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

HERE=Path(__file__).resolve().parent
PROJECT=HERE.parents[1]
WORKSPACE=PROJECT.parent
RUN=WORKSPACE/'graduation-experiment-results/chapter2_retrieval'
OUT=RUN/'experiments/single_pass/dev40'
SPLIT=RUN/'data'
QUESTIONS=SPLIT/'dev40/model/questions.json'
JUDGES=('gpt_sol','deepseek_flash')
METHODS=('graph','bm25','bge_m3')
MODELS=('qwen3-8b','qwen3-14b')
LOCK=threading.Lock()
RETRIEVAL_LOCK=threading.RLock()

def now(): return datetime.now(timezone.utc).isoformat()
def sha_bytes(b): return hashlib.sha256(b).hexdigest()
def sha(p): return sha_bytes(layout.resolve(p).read_bytes())
def load(p): return json.loads(layout.resolve(p).read_text(encoding='utf-8-sig'))
def save(p,obj):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);tmp=p.with_name(p.name+'.tmp')
    tmp.write_text(json.dumps(obj,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');os.replace(tmp,p)
def append(p,obj):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('a',encoding='utf-8') as f:f.write(json.dumps(obj,ensure_ascii=False)+'\n');f.flush();os.fsync(f.fileno())

def latest_recovery(cfg,qid):
    parent=OUT/'generation_recovery'/cfg/qid
    attempts=sorted(parent.glob('attempt_*'),key=lambda p:int(p.name.split('_')[-1])) if parent.exists() else []
    return attempts[-1] if attempts else None

def paths_and_runtime():
    sys.path[:0]=[str(PROJECT/'experiments/chapter2_round2'),str(PROJECT/'experiments/retrieval_method'),str(PROJECT/'src'),str(HERE)]
    import common
    common.ARCHIVE=RUN/'data/resources'
    common.RESOURCES=RUN/'data/resources'
    common.QUESTIONS=QUESTIONS
    return common

def prepare():
    if OUT.exists() and (OUT/'protocol.json').exists(): return load(OUT/'protocol.json')
    OUT.mkdir(parents=True,exist_ok=True)
    qs=load(QUESTIONS)
    assert len(qs)==40 and all(set(q)=={'id','question'} for q in qs)
    registry=__import__('central_execution').Registry()
    current=RUN/'data/resources'
    bindings={str(p.relative_to(WORKSPACE)):sha(p) for p in [QUESTIONS,SPLIT/'split_freeze.json',RUN/'data/resources/corpus-manifest.json',RUN/'data/resources/source-map.json',current/'graphs/selected.json',current/'indexes/bge_dense_v1/manifest.json',HERE/'judge_prompt.txt',HERE/'scoring_rules.json',HERE/'judge_contract.py',HERE/'judge_api_adapter.py']}
    protocol=dict(schema='single_pass_rag_dev40_v1',created_utc=now(),owner_authorization='2026-10-25 explicit user authorization',
      scope=dict(methods=list(METHODS),models=list(MODELS),questions=40,generation_sessions=240,judges=list(JUDGES),max_judge_requests=480,test160=False),
      execution=dict(query='exact original natural-language question',retrieval_calls=1,post_retrieval_tool_calls=0,model_tools=[],delivered_character_cap=6000,top_slots=10,temperature=0,thinking=False,input_output_combined_cap=32768,output_cap=2048),
      retrieval_identity='Frozen round2 GraphEngine/TextEngine implementations; method-local frozen graph/BM25/BGE index; fixed top 10; deterministic native expansion/ranking retained.',
      generation_prompt='Answer the original question using only the supplied retrieved evidence. If evidence is insufficient, say what is unknown and do not invent details. Preserve inline source citations using the supplied relative paths and line numbers. Give a direct, concise technical answer.',
      scoring=dict(prompt_sha256=sha(HERE/'judge_prompt.txt'),rules_sha256=sha(HERE/'scoring_rules.json'),contract_sha256=sha(HERE/'judge_contract.py'),judges=list(JUDGES),gpt_execution=dict(protocol='chat_completions',endpoint='https://xcmapi.org/v1/chat/completions',model='gpt-6-sol',reasoning_effort='low',response_format={'type':'json_object'},output_field='max_completion_tokens',output_cap=8192,read_timeout_seconds=900),deepseek_execution='current registry profile; independent request lane; no retries after unresolved/error'),
      questions_sha256=sha(QUESTIONS),split_freeze_sha256=sha(SPLIT/'split_freeze.json'),bindings=bindings,registry_sha256=registry.hashes)
    save(OUT/'authorization.json',dict(authorized=True,authorizer='project owner',scope=protocol['scope'],date='2026-10-25'))
    save(OUT/'protocol.json',protocol)
    save(OUT/'task_manifest.json',dict(tasks=[dict(config_id=f'{m}__{model}',method=m,model=model,question_id=q['id']) for model in MODELS for m in METHODS for q in qs],count=240))
    for name in ('generation','scoring','analysis'): (OUT/name).mkdir(exist_ok=True)
    return protocol

def get_engines(common):
    from retrieval import GraphEngine,TextEngine
    return {'graph':GraphEngine('graph'),'bm25':TextEngine('bm25'),'bge_m3':TextEngine('bge_m3')}

def retrieve(method,question,common,engine,folder):
    from retrieval import SlotsBackend
    from principia_core.retrieval.knowledge_qa import FrozenKnowledgeCorpus,KnowledgeToolSession,KnowledgeBudget
    corpus=FrozenKnowledgeCorpus(common.RESOURCES/'corpus',common.RESOURCES/'corpus-manifest.json')
    with RETRIEVAL_LOCK: slots,trace=engine.query(question)
    session=KnowledgeToolSession('bm25',corpus,SlotsBackend(slots),KnowledgeBudget(1,6000,6000))
    text=session.execute('search',{'query':question})
    ev=next((x for x in session.events if x['name']=='search'),{})
    ranking=trace.get('ranking',[])
    if isinstance(ranking,dict): ranking=ranking.get('items',[])
    save(folder/'retrieval.json',dict(method=method,query=question,query_sha256=sha_bytes(question.encode()),backend_calls=1,post_retrieval_calls=0,ranked_candidates=ranking[:10],trace=trace,delivery=text,delivered_characters=len(text),delivered_lines=ev.get('delivered_original_lines',[]),truncated=json.loads(text).get('truncated',False) if text else True,status=ev.get('status','failed'),seconds=ev.get('seconds')))
    return text,ev

def run_generation():
    save(OUT/'recovery_authorization.json',dict(authorized=True,owner_instruction='2026-10-25: resume after endpoint recovery; do not repeat successful generations; retain all prior failed attempts',endpoint_probe=dict(qwen3_8b_http=200,qwen3_14b_http=200,models=['Qwen3-8B','qwen3-14b']),recovery_attempt='up_to_three_recovery_attempts; only pre-request implementation/configuration failures may proceed after a failed model request',automatic_retries=0,test160=False))
    common=paths_and_runtime();from retrieval import GraphEngine,TextEngine
    from chapter2_qwen_routing import routed_client
    qs=load(QUESTIONS);engines={}
    for method in METHODS: engines[method]=GraphEngine('graph') if method=='graph' else TextEngine(method)
    sem={k:threading.Semaphore(8 if k=='qwen3-8b' else 20) for k in MODELS}
    def job(model,method,q):
        cfg=f'{method}__{model}';original=OUT/'generation'/cfg/q['id'];original_result=original/'result.json'
        if original_result.exists() and load(original_result).get('status')=='success': return load(original_result)
        if original_result.exists():
            prior=load(original_result)
            if prior.get('status') not in ('transport_error','exception','invalid_response','http_rejected'):
                return dict(status='not_retryable',config_id=cfg,question_id=q['id'],prior_status=prior.get('status'))
            parent=OUT/'generation_recovery'/cfg/q['id'];attempts=sorted(parent.glob('attempt_*'),key=lambda p:int(p.name.split('_')[-1])) if parent.exists() else []
            if any((a/'result.json').exists() and load(a/'result.json').get('status')=='success' for a in attempts):return load(next(a/'result.json' for a in attempts if load(a/'result.json').get('status')=='success'))
            if len(attempts)>=3:return dict(status='attempt_limit_reached',config_id=cfg,question_id=q['id'])
            if attempts:
                last=attempts[-1];last_result=load(last/'result.json') if (last/'result.json').exists() else {}
                had_request=bool(list((last/'model_requests').glob('*.json'))) if (last/'model_requests').exists() else False
                if last_result.get('status')=='transport_error' and had_request:
                    return dict(status='no_retry_after_transport_error',config_id=cfg,question_id=q['id'])
            attempt_no=(int(attempts[-1].name.split('_')[-1])+1) if attempts else 2
            recovery=parent/f'attempt_{attempt_no}';folder=recovery
            if folder.exists() and any(folder.iterdir()):return dict(status='partial_unresolved',config_id=cfg,question_id=q['id'])
        else: folder=original
        res=folder/'result.json'
        folder.mkdir(parents=True,exist_ok=True);start=time.monotonic();state=dict(config_id=cfg,method=method,model=model,question_id=q['id'],question=q['question'],started_utc=now())
        try:
            if original_result.exists() and (original/'retrieval.json').exists():
                evidence=load(original/'retrieval.json')['delivery'];ev={'status':'reused_prior_single_retrieval','delivered_original_lines':load(original/'retrieval.json').get('delivered_lines',[]),'seconds':0.0}
                save(folder/'retrieval.json',load(original/'retrieval.json'))
            else: evidence,ev=retrieve(method,q['question'],common,engines[method],folder)
            prompt='Question:\n'+q['question']+'\n\nRetrieved original-source evidence (JSON, including paths and line numbers):\n'+evidence+'\n\n'+load(OUT/'protocol.json')['generation_prompt']
            settings=PROJECT/'config/llm/.env'
            if model=='qwen3-8b':
                from central_execution import Registry
                registry=Registry();route=registry.resolve('qwen3_8b');key=registry.private_key('qwen3_8b')
                fd,temp_settings=tempfile.mkstemp(prefix='singlepass-qwen8-',suffix='.env');os.close(fd)
                Path(temp_settings).write_text('\n'.join(['QWEN_LOCAL_API_KEY='+key,'QWEN_LOCAL_8B_BASE_URL='+route['endpoint'].split('/chat/completions')[0].rsplit('/v1',1)[0]+'/v1','QWEN_LOCAL_8B_MODEL=Qwen3-8B','QWEN_LOCAL_MAX_CONCURRENCY=8'])+'\n',encoding='utf-8')
                try: client=routed_client(model,folder/'model_requests',settings_path=Path(temp_settings),timeout=900)
                finally: Path(temp_settings).unlink(missing_ok=True)
            else: client=routed_client(model,folder/'model_requests',settings_path=settings,timeout=900)
            apiid='qwen3-8b' if model=='qwen3-8b' else 'qwen3-14b'
            body=dict(model=apiid,messages=[{'role':'user','content':prompt}],temperature=0,max_tokens=2048,enable_thinking=False,stream=False)
            with sem[model]: rec=client(body,0)
            raw=rec.get('raw_response') or rec.get('response',{}).get('raw_response')
            if rec.get('status')!='response' or not raw: state.update(status=rec.get('status','invalid_response'),answer='',generation_failed=True,request_sha256=rec.get('request_sha256'))
            else:
                msg=raw['choices'][0]['message'];answer=msg.get('content') or ''
                if not answer: state.update(status='empty_answer',answer='',generation_failed=True)
                else: state.update(status='success',answer=answer,generation_failed=False,usage=raw.get('usage',{}),finish_reason=raw['choices'][0].get('finish_reason'),request_sha256=rec.get('request_sha256'),response_sha256=rec.get('raw_response_sha256'),actual_model=raw.get('model'))
        except Exception as e: state.update(status='exception',error_type=type(e).__name__,error=str(e)[:500],answer='',generation_failed=True)
        state.update(completed_utc=now(),seconds=round(time.monotonic()-start,3),retrieval_characters=load(folder/'retrieval.json').get('delivered_characters',0) if (folder/'retrieval.json').exists() else 0)
        save(res,state);append(OUT/'generation/ledger.jsonl',dict(config_id=cfg,question_id=q['id'],status=state['status'],request_sha256=state.get('request_sha256'),seconds=state['seconds']))
        return state
    jobs=[(model,method,q) for model in MODELS for method in METHODS for q in qs]
    with ThreadPoolExecutor(max_workers=28) as pool:
        futures=[pool.submit(job,*x) for x in jobs]
        for n,f in enumerate(as_completed(futures),1):
            try:r=f.result(); print(json.dumps({'generation':n,'config':r.get('config_id'),'qid':r.get('question_id'),'status':r.get('status')}),flush=True)
            except Exception as e: print(json.dumps({'generation_exception':type(e).__name__,'message':str(e)[:200]}),flush=True)

def scoring_items():
    import importlib
    core=importlib.import_module('scoring');dev=importlib.import_module('dev40_optimization');dc=importlib.import_module('dev40_scoring')
    from judge_contract import VERSION
    base=dev.SPLIT/'gold/dev40';annotations={x['id']:x for x in core.read(base/'annotations.json')};evidence=core.read(base/'evidence.json')
    qs={q['id']:q['question'] for q in core.read(dev.QUESTIONS)};result=[]
    for model in MODELS:
      for method in METHODS:
       cfg=f'{method}__{model}'
       for qid,question in qs.items():
        latest=latest_recovery(cfg,qid)
        rawfile=(latest/'result.json') if latest else OUT/'generation_recovery'/cfg/qid/'attempt_2/result.json'
        if not rawfile.exists(): rawfile=OUT/'generation'/cfg/qid/'result.json'
        if not rawfile.exists(): continue
        raw=core.read(rawfile);a=annotations[qid];sources=[];seen=set()
        for eid in a['required_evidence_ids']:
         e=evidence[eid]
         if e['path'] in seen:continue
         seen.add(e['path']);fp=RUN/'data/resources/corpus'/e['path']
         text='\n'.join('%d|%s'%(i,line) for i,line in enumerate(fp.read_text(encoding='utf-8-sig').splitlines(),1))
         sources.append(dict(path=e['path'],file_sha256=e['file_sha256'],text=text))
        item=dict(schema_version=VERSION,sample_id='SP'+hashlib.sha256((cfg+'|'+qid+'|'+str(raw.get('request_sha256'))).encode()).hexdigest()[:16],question=question,answer=raw.get('answer',''),generation_failed=raw.get('generation_failed',True),criteria=[dict(criterion_id='K%03d'%(i+1),claim=c['claim']) for i,c in enumerate(a['required_points'])],conditional=a['labels']['condition_discrimination'],sources=sources)
        result.append(dict(model=model,method=method,qid=qid,item=item,raw=raw))
    return result

def score(judge_filter=None):
    sys.path.insert(0,str(HERE));import dev40_scoring as dc
    from central_execution import Registry
    from judge_api_adapter import digest
    from judge_contract import joint_metrics
    import scoring as core
    items=scoring_items();registry=Registry();compact=set();preflight_failures=[]
    for x in items:
      if x['raw'].get('generation_failed'): continue
      try:
        _,profile,req,_=dc.request_for('gpt_sol',x['item'])
      except ValueError as exc:
        if 'exceeds' in str(exc): compact.add(x['qid'])
        else: preflight_failures.append(dict(sample_id=x['item']['sample_id'],reason=str(exc)))
    for x in items:
      if x['qid'] in compact:
        x['item']['sources']=[dict(s,text='\n'.join(line for line in s['text'].splitlines() if line.partition('|')[2].strip())) for s in x['item']['sources']]
    if compact:
      for x in items:
        if x['qid'] not in compact or x['raw'].get('generation_failed'): continue
        try: _,profile,req,_=dc.request_for('gpt_sol',x['item'])
        except ValueError as exc: preflight_failures.append(dict(sample_id=x['item']['sample_id'],reason=str(exc)))
    save(OUT/'scoring/packet.json',dict(schema_version='ch2_five_level_dual_eas',protocol_sha256=sha(OUT/'protocol.json'),items=[dict(model=x['model'],method=x['method'],qid=x['qid'],item=x['item']) for x in items],count=len(items),whitespace_compacted_question_ids=sorted(compact),preflight_failures=preflight_failures))
    preflight_ids={x['sample_id'] for x in preflight_failures}
    for judge in ([judge_filter] if judge_filter else JUDGES):
      profile=registry.judge_profile(judge)
      if judge=='gpt_sol':
       profile=deepcopy(profile);profile['output_token_cap']=8192
      # Reconcile valid saved HTTP responses from the previous parser wiring error; never resend them.
      for x in items:
       if x['raw'].get('generation_failed'): continue
       item=x['item'];folder=OUT/'scoring'/judge/item['sample_id']
       response_file=folder/'response.txt';parsed_file=folder/'parsed.json'
       if response_file.exists() and not parsed_file.exists():
        try:
         raw_response=json.loads(response_file.read_text(encoding='utf-8-sig'))
         observed=__import__('judge_api_adapter').usage(raw_response,profile['protocol'])
         if observed['output_tokens']>8192 or observed['input_tokens']+observed['output_tokens']>32768: raise ValueError('provider_budget_violation_stop_and_preserve_raw')
         reconciled=core.parse_current(profile,raw_response,item)
         save(parsed_file,reconciled);save(folder/'reconciliation.json',dict(status='valid_response_reparsed_offline',original_status=load(folder/'status.json') if (folder/'status.json').exists() else None,reason='fixed local parser module wiring; no request resent'))
        except Exception as exc:
         save(folder/'reconciliation.json',dict(status='reconcile_failed',error_type=type(exc).__name__,reason=str(exc)[:500],request_resent=False))
      stop=threading.Event()
      def one(x):
       item=x['item'];sid=item['sample_id'];folder=OUT/'scoring'/judge/sid
       if stop.is_set(): return dict(status='not_sent_stopped',judge=judge,sample_id=sid)
       if sid in preflight_ids:
        save(OUT/'scoring/preflight'/judge/(sid+'.json'),dict(status='not_sent_input_budget',judge=judge,sample_id=sid,reason=next(x['reason'] for x in preflight_failures if x['sample_id']==sid)));return dict(status='not_sent_input_budget',judge=judge,sample_id=sid)
       parsed=folder/'parsed.json';status=folder/'status.json'
       if parsed.exists(): return load(parsed)
       if folder.exists() and status.exists(): return load(status)
       folder.mkdir(parents=True,exist_ok=True)
       try:
        _,profile,req,_=dc.request_for(judge,item)
        # Match recent successful Sol execution exactly; only raise its output reservation.
        req['body']['max_completion_tokens' if judge=='gpt_sol' else 'max_tokens']=8192 if judge=='gpt_sol' else profile['output_token_cap']
        key=registry.private_key(judge);address=urlsplit(req['url']);conn=http.client.HTTPSConnection(address.hostname,address.port or 443,timeout=15,context=ssl.create_default_context())
        save(folder/'request.json',dict(request=req,profile=profile,protocol_sha256=sha(OUT/'protocol.json'),request_sha256=digest(req['body'])))
        append(OUT/'scoring'/judge/'ledger.jsonl',dict(sample_id=sid,started_utc=now(),request_sha256=digest(req['body']),actual_cost='Unknown'))
        conn.connect();conn.sock.settimeout(900 if judge=='gpt_sol' else 600)
        conn.request('POST',address.path,body=json.dumps(req['body'],ensure_ascii=False).encode(),headers={'Authorization':'Bearer '+key,'Content-Type':'application/json','Accept':'application/json'})
        response=conn.getresponse();rawtext=response.read().decode().replace(key,'[REDACTED]');(folder/'response.txt').write_text(rawtext,encoding='utf-8');conn.close()
        if response.status!=200: raise RuntimeError('http_'+str(response.status))
        raw=json.loads(rawtext)
        from judge_api_adapter import usage as parse_usage
        observed=parse_usage(raw,profile['protocol'])
        if observed['output_tokens']>8192 or observed['input_tokens']+observed['output_tokens']>32768:
         raise ValueError('provider_budget_violation_stop_and_preserve_raw')
        result=core.parse_current(profile,raw,item)
        save(parsed,result);state=dict(status='valid',judge=judge,sample_id=sid,usage=result['usage'],response_model=result['response_model'],seconds=None)
       except Exception as e:
        state=dict(status='failed',judge=judge,sample_id=sid,error_type=type(e).__name__,reason=str(e)[:600])
        stop.set()
       save(status,state);return state
      pending=[x for x in items if not x['raw'].get('generation_failed') and not (OUT/'scoring'/judge/x['item']['sample_id']/'parsed.json').exists()]
      maxworkers=2 if judge=='gpt_sol' else 1
      with ThreadPoolExecutor(max_workers=maxworkers) as pool:
       fs=[pool.submit(one,x) for x in pending]
       for f in as_completed(fs):
        r=f.result();print(json.dumps({'judge':judge,'sample_id':r.get('sample_id'),'status':r.get('status')}),flush=True)
        if stop.is_set():
         # Requests already in flight finish; no new retries are launched.
         pass

def analyze():
    from judge_contract import joint_metrics
    from judge_statistics import dual_eas
    items=scoring_items();out=[]
    for x in items:
      item=x['item'];scores={};
      for j in JUDGES:
       p=OUT/'scoring'/j/item['sample_id']/'parsed.json'
       if p.exists():
        r=load(p)['record'];scores[j]=dict(record=r,metrics=joint_metrics(r,[c['criterion_id'] for c in item['criteria']],item['conditional'],item['generation_failed']))
      if scores: out.append(dict(model=x['model'],method=x['method'],question_id=x['qid'],sample_id=item['sample_id'],generation_status=x['raw']['status'],answer=x['raw'].get('answer',''),usage=x['raw'].get('usage',{}),retrieval_characters=x['raw'].get('retrieval_characters',0),judge_scores=scores))
    save(OUT/'analysis/per_answer.json',out)
    # Aggregates only complete judge pairs; expose denominator and missingness.
    ag=[]
    for model in MODELS:
     for method in METHODS:
      rows=[r for r in out if r['model']==model and r['method']==method];metrics=[]
      for r in rows:
       if set(r['judge_scores'])==set(JUDGES):
        metrics.append({k:statistics.mean(r['judge_scores'][j]['metrics'][k] for j in JUDGES if isinstance(r['judge_scores'][j]['metrics'].get(k),(int,float))) for k in ('K','F','A','EAS_arith','EAS_geo')})
      ag.append(dict(model=model,method=method,n=len(rows),n_dual=len(metrics),means={k:statistics.mean([m[k] for m in metrics if isinstance(m.get(k),(int,float))]) if any(isinstance(m.get(k),(int,float)) for m in metrics) else None for k in ('K','F','A','EAS_arith','EAS_geo')},mean_retrieval_characters=statistics.mean([r['retrieval_characters'] for r in rows]) if rows else None,generation_success=sum(r['generation_status']=='success' for r in rows),generation_failures=sum(r['generation_status']!='success' for r in rows)))
    save(OUT/'analysis/aggregate.json',dict(rows=ag,paired_comparison='Populate Agentic pairing from existing canonical per-answer CSV after completion',test160_started=False))

if __name__=='__main__':
 import argparse
 p=argparse.ArgumentParser();p.add_argument('command',choices=['prepare','generate','score','score-deepseek','analyze']);a=p.parse_args()
 if a.command=='prepare': print(json.dumps(prepare(),ensure_ascii=False))
 elif a.command=='generate':prepare();run_generation()
 elif a.command=='score':score()
 elif a.command=='score-deepseek':score('deepseek_flash')
 else:analyze()
