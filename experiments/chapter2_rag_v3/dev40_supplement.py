"""One mechanistic Top-5 finalist, paired Dev-only transfer, exact-input reuse.

Never forces tool adoption or changes the frozen autonomous agent prompt.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
import hashlib
import http.client
import json
from pathlib import Path
import ssl
import sys
import threading
import time
from urllib.parse import urlsplit

import single_pass_dev40 as s
from central_execution import Registry, exclusive_lock
from dev40_retrieval_study import STUDY, FilteredGraph

ROOT=s.RUN/'experiments/agentic/dev40/supplement'
LOCK=threading.Lock()


def original(model,qid):
    cfg='graph__'+model
    folder=s.OUT/'generation'/cfg/qid
    choices=[folder]+sorted((s.OUT/'generation_recovery'/cfg/qid).glob('attempt_*'))
    good=[p for p in choices if (p/'result.json').exists() and s.load(p/'result.json').get('status')=='success']
    if not good:raise ValueError('Missing original successful generation')
    return good[0]


def prepare():
    questions=s.load(s.QUESTIONS)
    import csv
    types={r['id']:r['type'] for r in csv.DictReader((s.WORKSPACE/'graduation-datasets/chapter02_knowledge_qa/formal_v2_200/questions.csv').open(encoding='utf-8-sig'))}
    # Fixed IDs before observing finalist answer scores: first 3 IDs in each type.
    transfer=[]
    for typ in ('S0','S1','M0','M1'):
        transfer += sorted(q['id'] for q in questions if types[q['id']]==typ)[:3]
    assert len(transfer)==12
    definition=dict(schema='dev40_top5_finalist',created_utc=s.now(),
        finalist='top5',retrieval_config={'top_slots':5},
        original_baseline_protocol_sha256=s.sha(s.OUT/'protocol.json'),
        offline_evaluation_sha256=s.sha(STUDY/'offline_evaluation.json'),
        primary='Per-answer dual-judge arithmetic mean EAS_arith',
        secondary=['EAS_geo','K','F','A','necessary evidence recall','characters','tokens'],
        single_pass=dict(models=list(s.MODELS),questions=40,sessions=80,
            exact_input_reuse='Reuse baseline generation and scores only when original question, prompt and exact serialized evidence are identical'),
        agentic=dict(models=list(s.MODELS),question_ids=transfer,questions_per_model=12,sessions=24,
            baseline='Existing same-question graph Agentic; no repeated baseline calls',
            protocol='Unchanged autonomous QA; at most 8 tool calls; Top-5 candidate slots only'),
        limitations='Dev-selected finalist; 12 question stratified transfer diagnostic, no Test tuning, no global optimality or significance claim',
        source_sha256=s.sha(Path(__file__)),test160=False)
    ROOT.mkdir(parents=True,exist_ok=True)
    p=ROOT/'protocol.json'
    if p.exists():
        old=s.load(p)
        for k in definition:
            if k!='created_utc' and old[k]!=definition[k]:raise ValueError('Supplement binding drift '+k)
        return old
    s.save(p,definition)
    return definition


def client(folder,model):
    registry=Registry()
    # Registry keys use qwen3_8b / qwen3_14b.
    key=model.replace('-','_')
    route=registry.resolve(key);secret=registry.private_key(key)
    def call(body,turn):
        payload={**body,'model':route['api_model_id'],**route['wire_parameters']}
        if model=='qwen3-8b':payload.pop('enable_thinking',None)
        p=folder/'requests';p.mkdir(exist_ok=True)
        req=p/(str(turn).zfill(2)+'.request.json')
        if req.exists():raise RuntimeError('Existing request: reconcile, do not duplicate')
        s.save(req,dict(endpoint=route['endpoint'],body=payload,started_utc=s.now()))
        with LOCK:s.append(ROOT/'request_ledger.jsonl',dict(folder=str(folder),turn=turn,model=model,request_sha256=s.sha(req),actual_cost='Unknown'))
        address=urlsplit(route['endpoint']);ctx=ssl.create_default_context()
        if model=='qwen3-14b':ctx.minimum_version=ctx.maximum_version=ssl.TLSVersion.TLSv1_2
        conn=(http.client.HTTPSConnection(address.hostname,address.port or 443,timeout=15,context=ctx) if address.scheme=='https' else http.client.HTTPConnection(address.hostname,address.port or 80,timeout=15))
        try:
            conn.connect();conn.sock.settimeout(600)
            conn.request('POST',address.path,body=json.dumps(payload,ensure_ascii=False).encode(),headers={'Authorization':'Bearer '+secret,'Content-Type':'application/json'})
            response=conn.getresponse();text=response.read().decode('utf-8').replace(secret,'[REDACTED]')
            (p/(str(turn).zfill(2)+'.response.txt')).write_text(text,encoding='utf-8')
            if response.status!=200:return dict(status='http_rejected',http_status=response.status)
            raw=json.loads(text);usage=raw.get('usage',{})
            if raw.get('model') not in route['allowed_response_model_ids']:return dict(status='model_identity_mismatch',raw_response=raw)
            if any(type(usage.get(k)) is not int for k in ('prompt_tokens','completion_tokens')):return dict(status='usage_unknown',raw_response=raw)
            if usage['prompt_tokens']+usage['completion_tokens']>32768 or usage['completion_tokens']>payload['max_tokens']:return dict(status='provider_budget_violation',raw_response=raw)
            return dict(status='response',raw_response=raw,response={**raw,'model':model},actual_api_model=route['api_model_id'],request=payload)
        except (OSError,http.client.HTTPException) as exc:return dict(status='transport_error',error_type=type(exc).__name__)
        finally:conn.close()
    return call


def generate(mode):
    definition=prepare();common=s.paths_and_runtime()
    from principia_core.retrieval.knowledge_qa import FrozenKnowledgeCorpus,KnowledgeToolSession,KnowledgeBudget
    import principia_core.retrieval.knowledge_agent as agent
    from retrieval import SlotsBackend
    from chapter2_common_qa_interface import neutral_messages
    from chapter2_qa_deployment import prepared_messages,ANSWER_CHECKLIST
    from transformers import AutoTokenizer
    tokenizer=AutoTokenizer.from_pretrained(str(common.RESOURCES/'tokenizers/qwen3-14b'),local_files_only=True,trust_remote_code=False)
    corpus=FrozenKnowledgeCorpus(common.RESOURCES/'corpus',common.RESOURCES/'corpus-manifest.json')
    engine=FilteredGraph({'top_slots':5})
    qs=[q for q in s.load(s.QUESTIONS) if mode=='single_pass' or q['id'] in definition['agentic']['question_ids']]
    out=ROOT/mode;out.mkdir(exist_ok=True)
    protocol=dict(schema='dev40_supplement_scoring',scope=dict(generation_sessions=len(qs)*2),
        execution_mode=mode,parent_protocol_sha256=s.sha(ROOT/'protocol.json'),test160=False)
    if not (out/'protocol.json').exists():s.save(out/'protocol.json',protocol)
    else:assert s.load(out/'protocol.json')==protocol
    def job(model,q):
        cfg='top5__'+model;folder=out/'generation'/cfg/q['id']
        if (folder/'result.json').exists():return s.load(folder/'result.json')
        if (folder/'requests').exists():return dict(status='unknown_hold',model=model,qid=q['id'])
        folder.mkdir(parents=True,exist_ok=True)
        started=time.monotonic()
        if mode=='single_pass':
            ret=s.load(STUDY/'deliveries/top5'/q['id']/'retrieval.json')
            baseline=original(model,q['id']);oldret=s.load(baseline/'retrieval.json')
            if ret['delivery']==oldret['delivery']:
                r=s.load(baseline/'result.json')
                s.save(folder/'reuse.json',dict(source=str(baseline),source_sha256=s.sha(baseline/'result.json'),exact_delivery_equal=True))
                s.save(folder/'result.json',r);s.save(folder/'retrieval.json',ret)
                return dict(model=model,qid=q['id'],status='reused_identical_input')
            evidence=ret['delivery'];s.save(folder/'retrieval.json',ret)
            prompt='Question:\n'+q['question']+'\n\nRetrieved original-source evidence (JSON, including paths and line numbers):\n'+evidence+'\n\n'+s.load(s.OUT/'protocol.json')['generation_prompt']
            body=dict(model=model,messages=[dict(role='user',content=prompt)],temperature=0,max_tokens=2048,enable_thinking=False,stream=False)
            response=client(folder,model)(body,0)
            raw=response.get('raw_response',{});answer=raw.get('choices',[{}])[0].get('message',{}).get('content') or ''
            success=response['status']=='response' and bool(answer) and raw['choices'][0].get('finish_reason')=='stop'
            r=dict(model=model,question_id=q['id'],answer=answer,status='success' if success else response['status'],
                   generation_failed=not success,usage=raw.get('usage',{}),retrieval_characters=ret['delivered_characters'])
        else:
            class Backend:
                calls=0
                def search(self,query,limit):
                    with s.RETRIEVAL_LOCK:slots,trace=engine.query(query)
                    s.save(folder/'retrieval_traces'/(str(self.calls).zfill(2)+'.json'),dict(query=query,trace=trace));self.calls+=1
                    return SlotsBackend(slots).search(query,limit)
            tools=KnowledgeToolSession('bm25',corpus,Backend(),KnowledgeBudget(8,6000,24000))
            def transform(messages):
                result=neutral_messages(prepared_messages(messages,ANSWER_CHECKLIST))
                route=Registry().resolve(model.replace('-','_'));suffix=route.get('append_last_user_suffix')
                if suffix:
                    for m in reversed(result):
                        if m['role']=='user':m['content']+='\n'+suffix;break
                return result
            def count(messages):
                with LOCK:return len(tokenizer.apply_chat_template(messages,tokenize=True,add_generation_prompt=True,enable_thinking=False))
            transport=client(folder,model)
            def call(body,turn):
                payload=deepcopy(body);payload['messages']=transform(body['messages'])
                if count(payload['messages'])+payload['max_tokens']>32768:return dict(status='combined_context_budget_exhausted')
                return transport(payload,turn)
            r=agent.AutonomousKnowledgeAgent(model,tools,call,lambda m:count(transform(m)),agent.ModelBudget(input_tokens_per_request=30720)).run(q['question'])
            r.update(question_id=q['id'],generation_failed=r['status']!='answered',delivered_lines=[dict(path=p,line=n) for p,n in sorted(tools.delivered_lines)])
        r.update(config_id=cfg,completed_utc=s.now(),seconds=round(time.monotonic()-started,3),protocol_sha256=s.sha(ROOT/'protocol.json'))
        s.save(folder/'result.json',r)
        return dict(model=model,qid=q['id'],status=r['status'])
    with exclusive_lock(out/'generation.lock'):
        with ThreadPoolExecutor(max_workers=6) as pool:
            fs=[pool.submit(job,m,q) for m in s.MODELS for q in qs]
            for n,f in enumerate(as_completed(fs),1):print(json.dumps(dict(n=n,mode=mode,result=f.result())),flush=True)


def packet(mode):
    out=ROOT/mode;definition=prepare()
    original_packet=s.load(s.OUT/'scoring/packet.json')
    baseline={(r['model'],r['qid']):r['item'] for r in original_packet['items'] if r['method']=='graph'}
    rows=[]
    for model in s.MODELS:
        for q in s.load(s.QUESTIONS):
            if mode=='agentic' and q['id'] not in definition['agentic']['question_ids']:continue
            folder=out/'generation'/('top5__'+model)/q['id'];raw=s.load(folder/'result.json')
            item=deepcopy(baseline[model,q['id']]);item['answer']=raw.get('answer') or '';item['generation_failed']=raw.get('generation_failed',False)
            reused=(folder/'reuse.json').exists()
            if not reused:item['sample_id']='SP'+hashlib.sha256((mode+'|top5|'+model+'|'+q['id']+'|'+s.sha(folder/'result.json')).encode()).hexdigest()[:16]
            rows.append(dict(model=model,method='graph_top5',qid=q['id'],item=item))
            if reused:
                for judge in s.JUDGES:
                    source=s.OUT/'scoring'/judge/item['sample_id']/'parsed.json'
                    if source.exists():
                        target=out/'scoring'/judge/item['sample_id']/'parsed.json'
                        if not target.exists():s.save(target,s.load(source))
                        s.save(target.parent/'reuse.json',dict(source=str(source),sha256=s.sha(source),exact_input_equal=True))
    destination=out/'scoring/packet.json'
    value=dict(count=len(rows),items=rows,protocol_sha256=s.sha(out/'protocol.json'))
    if destination.exists() and s.load(destination)!=value:raise ValueError('Never change an existing requested packet')
    if not destination.exists():s.save(destination,value)
    print(json.dumps(dict(mode=mode,items=len(rows),generation_failures=sum(x['item']['generation_failed'] for x in rows))))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=['prepare','generate','packet']);p.add_argument('--mode',choices=['single_pass','agentic'],default='single_pass');a=p.parse_args()
    if a.command=='prepare':print(json.dumps(prepare(),ensure_ascii=False))
    elif a.command=='generate':generate(a.mode)
    else:packet(a.mode)
