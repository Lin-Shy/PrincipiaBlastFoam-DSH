"""Dev40-only resumable generation. No Gold/scoring reads; no Test execution.

Called by dev40_optimization.py. Owner's 2026-10-24 instruction authorizes the
finite 26-candidate matrix without repeating monetary estimates.
"""
import runtime_layout as layout
from concurrent.futures import ThreadPoolExecutor
from collections import Counter
from copy import deepcopy
import hashlib
import http.client
import json
import os
from pathlib import Path
import ssl
import sys
import threading
import time
from urllib.parse import urlsplit

from central_execution import DEFAULT_RUN,PROJECT,Registry,now,sha,read,save,exclusive_lock
import dev40_optimization as dev

ROOT=dev.ROOT
OLD=DEFAULT_RUN/'experiments/agentic/reused_inputs'
LOCK=threading.Lock()
RETRIEVAL=threading.RLock()
INFRA={'http_rejected','transport_error','invalid_response','usage_unknown','model_identity_mismatch',
       'provider_budget_violation','infrastructure_exception'}


def update(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.tmp');temp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');os.replace(temp,path)


def endpoint_migration(root=None):
    """Explicit endpoint-only continuation; retain the original execution identity."""
    root=Path(root) if root is not None else ROOT
    file=root/'endpoint_migration.json'
    if not file.exists():return None
    receipt=read(file);original=read(root/'execution.json')
    if receipt['original_execution_sha256']!=sha(root/'execution.json'):
        raise ValueError('Endpoint migration execution binding changed')
    if receipt['original_source_sha256']!=original['source_sha256'] or not layout.source_equivalent(Path(__file__).name,receipt['active_source_sha256'],sha(Path(__file__))):
        raise ValueError('Endpoint migration runner binding changed')
    if (receipt['model_key'],receipt['old_endpoint'],receipt['new_endpoint'])!=(
            'qwen3_8b','http://192.168.31.247:8001/v1/chat/completions','http://192.168.31.205:8001/v1/chat/completions'):
        raise ValueError('Unapproved endpoint migration')
    return receipt


def effective_configurations(configs,root=None):
    receipt=endpoint_migration(root);result=deepcopy(configs)
    if receipt:
        for config in result:
            if config['model_key']==receipt['model_key']:
                if config['endpoint']!=receipt['old_endpoint'] or config['api_model_id']!='Qwen3-8B':
                    raise ValueError('Endpoint migration configuration mismatch')
                config['endpoint']=receipt['new_endpoint']
    return result


def bind_execution(spec,previous,receipt):
    expected=deepcopy(previous);actual=deepcopy(spec)
    for value in (expected,actual):value.pop('created_utc',None)
    if receipt:
        if actual['source_sha256']!=receipt['active_source_sha256'] or expected['source_sha256']!=receipt['original_source_sha256']:
            raise ValueError('Endpoint migration source mismatch')
        actual['source_sha256']=expected['source_sha256']
    if actual!=expected:raise ValueError('Active generation execution binding changed')


def prepare():
    if (DEFAULT_RUN/'release/manifests/test160_manifest.json').exists():
        layout.validate_manifest()
        previous=read(ROOT/'execution.json');previous['configurations']=effective_configurations(previous['configurations'])
        return previous,read(dev.QUESTIONS)
    matrix=read(ROOT/'candidate_matrix.json');short=read(ROOT/'shortlist.json');qs=read(dev.QUESTIONS)
    if sha(ROOT/'candidate_matrix.json')!=short['matrix_sha256']:raise ValueError('Candidate matrix drift')
    if len(qs)!=40 or any(set(q)!={'id','question'} for q in qs):raise ValueError('Only exact Dev40 production input allowed')
    configs=[c for c in matrix['configurations'] if c['config_id'] in short['active_configuration_ids']]
    if len(configs)!=26:raise ValueError('Only the 26 selected configurations allowed')
    registry=Registry();bindings={}
    # Verify the existing implementation, tokenizer, corpus, graph and dense indexes.
    old_config=read(OLD/'generation_config.pending.json')
    for relative,expected in old_config['resource_bindings'].items():
        if sha(PROJECT.parent/relative)!=expected:raise ValueError('Frozen generation resource drift: '+relative)
        bindings[relative]=expected
    roots={'src':PROJECT/'src','chapter2_round2':PROJECT/'experiments/chapter2_round2','retrieval_method':PROJECT/'experiments/retrieval_method'}
    for folder,target in roots.items():
        for file in (OLD/'runtime_snapshot'/folder).rglob('*.py'):
            relative=file.relative_to(OLD/'runtime_snapshot'/folder)
            if relative.as_posix()=='principia_core/__init__.py':continue # package bootstrap, not agent/retrieval logic
            live=target/relative
            if sha(file)!=sha(live):raise ValueError('Initial generation implementation drift: '+str(relative))
            bindings[str(live.relative_to(PROJECT.parent))]=sha(live)
    spec=dict(created_utc=now(),owner_instruction='2026-10-24: run Dev40 generation concurrently with final audit; no Test160',
        configurations=configs,question_ids=[q['id'] for q in qs],questions_sha256=sha(dev.QUESTIONS),
        split_freeze_sha256=sha(dev.SPLIT/'split_freeze.json'),matrix_sha256=sha(ROOT/'candidate_matrix.json'),
        shortlist_sha256=sha(ROOT/'shortlist.json'),source_sha256=sha(Path(__file__)),bindings=bindings,
        registry=registry.hashes,concurrency={'qwen3_8b':8,'qwen3_14b':20},maximum_sessions=1040,
        max_physical_requests=9360,automatic_retries=0,content_retries=0,combined_tokens=32768,
        scoring_independent=True,judging_requires_audit_acceptance=True,test160_authorized=False)
    file=ROOT/'execution.json'
    if file.exists():
        previous=read(file)
        bind_execution(spec,previous,endpoint_migration())
    else:save(file,spec)
    completion=read(OLD/'generation_completion.json');plan=read(OLD/'session_plan.json');qmap={q['id']:q['question'] for q in qs}
    reused=[]
    for s in plan['sessions']:
        cfg=next(c for c in configs if c['model_key']=='qwen3_14b' and c['method_id']==s['method_id'])
        original=OLD/s['result_path'];r=read(original)
        if sha(original)!=completion['results'][s['session_id']] or r['protocol_sha256']!=completion['protocol_sha256']:
            raise ValueError('Original Dev120 answer binding changed')
        if r['id']!=s['question_id'] or r['arm']!=s['method_id'] or r['model']!='qwen3-14b':raise ValueError('Reuse identity mismatch')
        if r['question_sha256']!=hashlib.sha256(qmap[r['id']].encode()).hexdigest():raise ValueError('Reuse question mismatch')
        if r['knowledge_budget']!=dict(tool_calls=8,tool_characters=6000,total_characters=24000):raise ValueError('Reuse knowledge budget mismatch')
        if r['model_budget']!=dict(input_tokens_per_request=30720,input_tokens_total=196608,output_tokens_per_request=2048,output_tokens_total=16384,final_output_reserve=2048):raise ValueError('Reuse model budget mismatch')
        reused.append(dict(config_id=cfg['config_id'],question_id=r['id'],source_path=str(original.relative_to(DEFAULT_RUN)),
            source_sha256=sha(original),status=r['status'],original_protocol_sha256=r['protocol_sha256']))
    file=ROOT/'reuse.json'
    value=dict(answers=reused,count=len(reused),raw_answers_copied=False,old_scores_reused=False,implementation_and_resource_identity_verified=True)
    if file.exists() and read(file)!=value:raise ValueError('Reuse mapping changed')
    if not file.exists():save(file,value)
    spec['configurations']=effective_configurations(spec['configurations'])
    return spec,qs


def execute(model=None,limit=None):
    spec,questions=prepare();registry=Registry()
    routes={k:registry.resolve(k) for k in spec['concurrency']}
    keys={k:registry.private_key(k) for k in routes} # finite run authorized by current owner instruction
    for c in spec['configurations']:
        route=routes[c['model_key']]
        if c['endpoint']!=route['endpoint'] or c['api_model_id']!=route['api_model_id']:raise ValueError('Generation route drift')
    os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',TOKENIZERS_PARALLELISM='false')
    sys.path[:0]=[str(PROJECT/'experiments/chapter2_round2'),str(PROJECT/'experiments/retrieval_method'),str(PROJECT/'src')]
    import common
    common.ARCHIVE=DEFAULT_RUN/'data/resources';common.RESOURCES=DEFAULT_RUN/'data/resources';common.QUESTIONS=dev.QUESTIONS
    from chapter2_knowledge_input_guard import install
    install(dev.QUESTIONS)
    from retrieval import GraphEngine,TextEngine,SlotsBackend,E5Rank
    from text_baselines import ParentBM25,RRF
    from principia_core.retrieval.knowledge_qa import FrozenKnowledgeCorpus,KnowledgeToolSession,KnowledgeBudget
    import principia_core.retrieval.knowledge_agent as agent
    from chapter2_basic_search_tools import BasicSearchSession,basic_specs
    from chapter2_common_qa_interface import neutral_messages
    from chapter2_qa_deployment import prepared_messages,ANSWER_CHECKLIST
    from transformers import AutoTokenizer
    original_specs=agent.tool_specs
    agent.tool_specs=lambda method:basic_specs() if method=='basic_search' else original_specs(method)
    tokenizer=AutoTokenizer.from_pretrained(str(common.RESOURCES/'tokenizers/qwen3-14b'),local_files_only=True,trust_remote_code=False)
    corpus=FrozenKnowledgeCorpus(common.RESOURCES/'corpus',common.RESOURCES/'corpus-manifest.json')
    engines={};stopped={k:threading.Event() for k in routes}
    def engine(method):
        with RETRIEVAL:
            if method not in engines:
                if method in dev.GRAPH:value=GraphEngine(method)
                elif method in ('bm25','bge_m3','e5'):value=TextEngine(method)
                else:
                    value=TextEngine.__new__(TextEngine);value.method=method;value.bm25=engine('bm25').bm25
                    if method=='bm25_parent':value.parent=ParentBM25(value.bm25)
                    elif method=='bm25_bge_m3':value.rrf=RRF(value.bm25,engine('bge_m3').dense)
                    elif method=='bm25_e5':value.rrf=RRF(value.bm25,E5Rank(engine('e5').e5))
                    else:raise ValueError('Unregistered method')
                engines[method]=value
            return engines[method]
    reused={(r['config_id'],r['question_id']) for r in read(ROOT/'reuse.json')['answers']}
    jobs=[(c,q) for c in spec['configurations'] for q in questions if not model or c['model_key']==model]
    # First real jobs validate direct routing while dedicated backends initialize lazily.
    jobs.sort(key=lambda pair:(pair[0]['method_id']!='direct',pair[0]['config_id'],pair[1]['id']))
    jobs=[(c,q) for c,q in jobs if (c['config_id'],q['id']) not in reused]
    if limit:jobs=jobs[:limit]
    def transform(messages,cfg):
        result=prepared_messages(messages,ANSWER_CHECKLIST)
        if cfg['method_id']!='basic':result=neutral_messages(result)
        suffix=routes[cfg['model_key']].get('append_last_user_suffix')
        if suffix:
            for message in reversed(result):
                if message['role']=='user':message['content']+='\n'+suffix;break
        return result
    def count(messages):
        with LOCK:return len(tokenizer.apply_chat_template(messages,tokenize=True,add_generation_prompt=True,enable_thinking=False))
    def worker(job):
        cfg,q=job;key=cfg['model_key'];folder=ROOT/'generation'/cfg['config_id']/q['id'];result_file=folder/'result.json'
        if result_file.exists():
            prior=read(result_file)
            if prior.get('execution_sha256')!=sha(ROOT/'execution.json') or prior['id']!=q['id'] or prior['config_id']!=cfg['config_id']:raise ValueError('Existing result binding mismatch')
            return
        if stopped[key].is_set():return
        if folder.exists():raise RuntimeError('Partial session exists; reconcile without duplicate requests: '+str(folder))
        folder.mkdir(parents=True);save(folder/'claim.json',dict(started_utc=now(),pid=os.getpid(),config_id=cfg['config_id'],question_id=q['id']))
        started=time.monotonic();method=cfg['method_id']
        try:
            if method=='direct':tools=KnowledgeToolSession('none')
            elif method=='basic':tools=BasicSearchSession(corpus,KnowledgeBudget())
            else:
                class Backend:
                    calls=0
                    def search(self,query,limit):
                        with RETRIEVAL:slots,trace=engine(method).query(query)
                        save(folder/'retrieval_traces'/(str(self.calls).zfill(2)+'.json'),dict(query=query,trace=trace));self.calls+=1
                        return SlotsBackend(slots).search(query,limit)
                tools=KnowledgeToolSession('bm25',corpus,Backend(),KnowledgeBudget())
            def client(body,turn):
                route=routes[key];secret=keys[key];payload={**body,'model':route['api_model_id'],'messages':transform(body['messages'],cfg),**route['wire_parameters']}
                if key=='qwen3_8b':payload.pop('enable_thinking',None)
                request_count=count(payload['messages'])
                if request_count+payload['max_tokens']>32768:return dict(status='combined_context_budget_exhausted')
                request_dir=folder/'requests';request_dir.mkdir(exist_ok=True)
                with LOCK:
                    ledger=ROOT/'request_ledger.jsonl'
                    event=dict(started_utc=now(),config_id=cfg['config_id'],question_id=q['id'],turn=turn,model_key=key,actual_cost='Unknown',
                        endpoint=route['endpoint'],endpoint_migration_sha256=sha(ROOT/'endpoint_migration.json') if (ROOT/'endpoint_migration.json').exists() else None)
                    with ledger.open('a',encoding='utf-8') as stream:stream.write(json.dumps(event)+'\n');stream.flush();os.fsync(stream.fileno())
                    save(request_dir/(str(turn).zfill(2)+'.request.json'),dict(url=route['endpoint'],body=payload,input_tokens_estimated=request_count))
                address=urlsplit(route['endpoint']);context=ssl.create_default_context()
                if key=='qwen3_14b':context.minimum_version=context.maximum_version=ssl.TLSVersion.TLSv1_2
                conn=(http.client.HTTPSConnection(address.hostname,address.port or 443,timeout=15,context=context) if address.scheme=='https' else http.client.HTTPConnection(address.hostname,address.port or 80,timeout=15))
                try:
                    conn.connect();conn.sock.settimeout(240)
                    conn.request('POST',address.path,body=json.dumps(payload,ensure_ascii=False).encode(),headers={'Authorization':'Bearer '+secret,'Content-Type':'application/json'})
                    response=conn.getresponse();text=response.read().decode('utf-8').replace(secret,'[REDACTED]')
                    (request_dir/(str(turn).zfill(2)+'.response.txt')).write_text(text,encoding='utf-8')
                    if response.status!=200:return dict(status='http_rejected',http_status=response.status)
                    raw=json.loads(text)
                    if raw.get('model') not in route['allowed_response_model_ids']:return dict(status='model_identity_mismatch',raw_response=raw)
                    usage=raw.get('usage',{})
                    if any(type(usage.get(k)) is not int or usage[k]<0 for k in ('prompt_tokens','completion_tokens')):return dict(status='usage_unknown',raw_response=raw)
                    if usage['prompt_tokens']+usage['completion_tokens']>32768 or usage['completion_tokens']>payload['max_tokens']:return dict(status='provider_budget_violation',raw_response=raw)
                    return dict(status='response',raw_response=raw,response={**raw,'model':cfg['logical_model']},actual_api_model=route['api_model_id'],request=payload)
                except (OSError,http.client.HTTPException) as exc:return dict(status='transport_error',error_type=type(exc).__name__)
                except (ValueError,KeyError,TypeError) as exc:return dict(status='invalid_response',error_type=type(exc).__name__)
                finally:conn.close()
            budget=agent.ModelBudget(input_tokens_per_request=30720)
            result=agent.AutonomousKnowledgeAgent(cfg['logical_model'],tools,client,lambda m:count(transform(m,cfg)),budget).run(q['question'])
            result.update(id=q['id'],arm=method,config_id=cfg['config_id'],actual_api_model=routes[key]['api_model_id'],
                execution_sha256=sha(ROOT/'execution.json'),question_sha256=hashlib.sha256(q['question'].encode()).hexdigest(),
                split_freeze_sha256=spec['split_freeze_sha256'],delivered_lines=[dict(path=p,line=n) for p,n in sorted(tools.delivered_lines)])
        except Exception as exc:result=dict(id=q['id'],arm=method,config_id=cfg['config_id'],status='infrastructure_exception',error_type=type(exc).__name__,execution_sha256=sha(ROOT/'execution.json'),answer=None)
        result.update(completed_utc=now(),seconds=round(time.monotonic()-started,3),actual_endpoint=routes[key]['endpoint'],
            endpoint_migration_sha256=sha(ROOT/'endpoint_migration.json') if (ROOT/'endpoint_migration.json').exists() else None);save(result_file,result)
        if result['status'] in INFRA:stopped[key].set()
        print(json.dumps(dict(model=key,config=cfg['config_id'],question=q['id'],status=result['status'],seconds=result['seconds'])),flush=True)
    with exclusive_lock(ROOT/'generation.lock'):
        def lane(key):
            with ThreadPoolExecutor(max_workers=spec['concurrency'][key]) as pool:list(pool.map(worker,[j for j in jobs if j[0]['model_key']==key]))
        with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(lane,[model] if model else list(routes)))
    statuses=Counter(read(f)['status'] for f in (ROOT/'generation').glob('*/*/result.json'))
    update(ROOT/'generation_status.json',dict(updated_utc=now(),reused_answers=len(reused),new_answers=sum(statuses.values()),
        statuses=dict(statuses),expected_sessions=1040,complete=len(reused)+sum(statuses.values())==1040,
        stopped_models=[key for key in stopped if stopped[key].is_set()],test160_started=False))


def main(args):
    if args.command=='run':execute(getattr(args,'model',None),getattr(args,'limit',None))
