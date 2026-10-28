"""Dev-only runner. Dry-run/retrieval-check forbid network; execute requires future exact paid approval.

No .env reading, implicit routing, retries, Test generation or judge API support.
"""
import argparse
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import sys


def read(p):return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def sha(p):
    h=hashlib.sha256()
    with Path(p).open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()
def save(p,x):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('x',encoding='utf-8') as f:json.dump(x,f,ensure_ascii=False,indent=2);f.write('\n')


def preflight(config_path):
    cfg=read(config_path);root=Path(cfg['workspace_root']);out=root/cfg['experiment_directory']
    assert sha(Path(__file__))==cfg['runner_sha256'],'Runner source drift'
    assert sha(root/cfg['split_directory']/'split_freeze.json')==cfg['split_freeze_sha256'],'Split freeze drift'
    freeze=read(root/cfg['split_directory']/'split_freeze.json')
    for rel,h in freeze['files'].items():assert sha(root/cfg['split_directory']/rel)==h,'Frozen split file drift'
    assert sha(root/cfg['questions_file'])==cfg['questions_sha256'],'Question file drift'
    qs=read(root/cfg['questions_file']);assert len(qs)==len({q['id'] for q in qs})==40 and all(set(q)=={'id','question'} for q in qs)
    plan=read(out/'session_plan.json');assert sha(out/'session_plan.json')==cfg['session_plan_sha256']
    expected={(q['id'],m) for q in qs for m in ['graph','bm25','bge_m3']}
    assert len(plan['sessions'])==120 and {(s['question_id'],s['method_id']) for s in plan['sessions']}==expected,'Not exact Dev40 x3'
    assert cfg['methods']==['graph','bm25','bge_m3'] and cfg['sessions']==120 and cfg['question_count']==40 and cfg['concurrency']==1
    assert cfg['logical_model']=='qwen3-14b' and cfg['temperature']==0 and cfg['enable_thinking'] is False
    assert cfg['combined_context_tokens']==32768
    assert cfg['model_budget']['input_tokens_per_request']+cfg['model_budget']['output_tokens_per_request']<=32768
    assert cfg['knowledge_budget']['tool_calls']+1<=cfg['max_physical_requests_per_session']<=9
    for rel,h in cfg['resource_bindings'].items():assert sha(root/rel)==h,'Resource drift: '+rel
    for rel,h in cfg['runtime_bindings'].items():assert sha(out/rel)==h,'Snapshot drift: '+rel
    assert cfg['transport_attempts']==1 and cfg['content_retries']==0
    return cfg,root,out,qs,plan


def paid_gate(cfg,config_path,approval_path):
    if approval_path is None:raise PermissionError('No paid API authorization: supply future owner-approved, hash-bound authorization')
    approval=read(approval_path)
    if not (approval.get('approved') is True and approval.get('owner_instruction') and
        approval.get('scope')=='dev120_generation_only' and approval.get('generation_config_sha256')==sha(config_path) and
        approval.get('max_sessions')==120 and approval.get('max_physical_requests')==1080 and cfg.get('api_authorized') is True):
        raise PermissionError('No matching paid authorization')
    if not all(isinstance(cfg.get(k),str) and cfg[k].strip() for k in ['api_model_id','expected_response_model_id','endpoint','api_key_environment_variable']):
        raise PermissionError('Concrete API identity and endpoint remain pending')
    if not cfg['endpoint'].startswith('https://'):raise PermissionError('Explicit HTTPS endpoint required')
    b=cfg['budget']
    if b['approved'] is not True or not b['currency'] or any(b.get(k) is None or Decimal(str(b[k]))<=0 for k in ['hard_limit','input_price_per_million','output_price_per_million']):
        raise PermissionError('Positive approved tariff and hard budget required')


def offline_guard():
    def hook(event,args):
        if event in {'socket.connect','socket.connect_ex','socket.getaddrinfo'}:raise PermissionError('Offline mode: network disabled')
    sys.addaudithook(hook)


def runtime(cfg,root,out):
    os.environ['HF_HUB_OFFLINE']='1';os.environ['TRANSFORMERS_OFFLINE']='1'
    snap=out/'runtime_snapshot'
    sys.path[:0]=[str(snap/'chapter2_round2'),str(snap/'retrieval_method'),str(snap/'src')]
    import common
    common.PROJECT=root/'PrincipiaBlastFoam-DSH';common.WORKSPACE=root;common.ARCHIVE=root/'graduation-experiment-results/chapter2_retrieval/current/provenance'
    common.RESOURCES=common.ARCHIVE.parent.parent/'resources';common.QUESTIONS=root/cfg['questions_file']
    common.GRAPH=common.ARCHIVE.parent/'revision_200_20261019_002/graphs/selected.json'
    common.LEGACY=snap/'retrieval_method'
    sys.path[:0]=[str(snap/'chapter2_round2'),str(snap/'retrieval_method'),str(snap/'src')]
    from chapter2_knowledge_input_guard import install
    install(common.QUESTIONS)
    from retrieval import GraphEngine,TextEngine,SlotsBackend
    return common,GraphEngine,TextEngine,SlotsBackend


class PaidClient:
    def __init__(self,cfg,out,folder,counter):
        self.cfg,self.out,self.folder,self.counter=cfg,out,folder,counter
        self.calls=0
    def __call__(self,body,turn):
        # Reservation at declared tariffs is durable and conservative; never auto-refund failures.
        cfg=self.cfg;input_count=self.counter(body['messages']);maxout=body['max_tokens']
        if input_count+maxout>cfg['combined_context_tokens']:return dict(status='combined_context_budget_exhausted')
        ledger=self.out/'budget_ledger.jsonl';events=[json.loads(x) for x in ledger.read_text(encoding='utf-8').splitlines()] if ledger.exists() else []
        reserve=(Decimal(cfg['model_budget']['input_tokens_per_request'])*Decimal(str(cfg['budget']['input_price_per_million']))+Decimal(maxout)*Decimal(str(cfg['budget']['output_price_per_million'])))/Decimal(1000000)
        if self.calls>=cfg['max_physical_requests_per_session'] or len(events)>=cfg['max_physical_requests_total'] or sum((Decimal(e['reserved_cost']) for e in events),Decimal(0))+reserve>Decimal(str(cfg['budget']['hard_limit'])):
            return dict(status='paid_budget_exhausted')
        if not os.environ.get(cfg['api_key_environment_variable']):raise PermissionError('Approved key environment variable unset')
        self.folder.mkdir(parents=True,exist_ok=True);request_path=self.folder/(str(turn).zfill(2)+'.request.json')
        payload={**body,'model':cfg['api_model_id']};save(request_path,payload)
        with ledger.open('a',encoding='utf-8') as f:f.write(json.dumps(dict(request_path=str(request_path),reserved_cost=str(reserve),input_tokens=input_count,max_output_tokens=maxout,protocol_sha256=cfg['_protocol_sha256']))+'\n')
        self.calls+=1
        from urllib.request import Request,build_opener,ProxyHandler
        from urllib.error import HTTPError,URLError
        key=os.environ[cfg['api_key_environment_variable']]
        try:
            req=Request(cfg['endpoint'],data=json.dumps(payload,ensure_ascii=False).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+key})
            # One physical attempt; disable inherited proxy and redirects.
            from urllib.request import HTTPRedirectHandler
            class NoRedirect(HTTPRedirectHandler):
                def redirect_request(self,*args,**kw):return None
            with build_opener(ProxyHandler({}),NoRedirect()).open(req,timeout=180) as response:raw_text=response.read().decode('utf-8')
            (self.folder/(str(turn).zfill(2)+'.response.txt')).write_text(raw_text.replace(key,'[REDACTED]'),encoding='utf-8')
            raw=json.loads(raw_text);save(self.folder/(str(turn).zfill(2)+'.response.json'),raw)
            if raw.get('model')!=cfg['expected_response_model_id']:return dict(status='model_identity_mismatch',raw_response=raw)
            usage=raw.get('usage',{})
            if any(type(usage.get(k)) is not int or usage[k]<0 for k in ['prompt_tokens','completion_tokens']):return dict(status='usage_unknown',raw_response=raw)
            if usage['prompt_tokens']>cfg['model_budget']['input_tokens_per_request'] or usage['completion_tokens']>maxout or usage['prompt_tokens']+maxout>32768:
                return dict(status='provider_budget_violation',raw_response=raw)
            # A provider token count exceeding the reservation invalidates monetary accounting: stop.
            if usage['prompt_tokens']>input_count:return dict(status='token_count_mismatch',raw_response=raw)
            return dict(status='response',raw_response=raw,response={**raw,'model':cfg['logical_model']},actual_api_model=cfg['api_model_id'])
        except HTTPError as exc:return dict(status='http_rejected',http_status=exc.code)
        except (URLError,TimeoutError,ConnectionError):return dict(status='transport_error')
        except (ValueError,KeyError,TypeError):return dict(status='invalid_response')


def execute(cfg,root,out,qs,plan):
    common,GraphEngine,TextEngine,SlotsBackend=runtime(cfg,root,out)
    from principia_core.retrieval.knowledge_agent import AutonomousKnowledgeAgent,ModelBudget
    from principia_core.retrieval.knowledge_qa import FrozenKnowledgeCorpus,KnowledgeToolSession,KnowledgeBudget
    from chapter2_common_qa_interface import neutral_messages
    from chapter2_qa_deployment import prepared_messages,ANSWER_CHECKLIST
    from transformers import AutoTokenizer
    tok=AutoTokenizer.from_pretrained(str(common.RESOURCES/'tokenizers/qwen3-14b'),local_files_only=True,trust_remote_code=False)
    def transformed(messages):return neutral_messages(prepared_messages(messages,ANSWER_CHECKLIST))
    def count_actual(messages):return len(tok.apply_chat_template(messages,tokenize=True,add_generation_prompt=True,enable_thinking=False))
    def count(messages):return count_actual(transformed(messages))
    engines={};qmap={q['id']:q['question'] for q in qs}
    corpus=FrozenKnowledgeCorpus(common.RESOURCES/'corpus',common.RESOURCES/'corpus-manifest.json')
    bad={'http_rejected','transport_error','invalid_response','usage_unknown','model_identity_mismatch','provider_budget_violation',
        'provider_output_budget_violation','token_count_mismatch','paid_budget_exhausted','combined_context_budget_exhausted'}
    for s in plan['sessions']:
        folder=out/s['output_directory'];result_path=out/s['result_path']
        if result_path.exists():
            prior=read(result_path)
            if prior.get('protocol_sha256')!=cfg['_protocol_sha256'] or prior.get('id')!=s['question_id'] or prior.get('arm')!=s['method_id']:
                raise RuntimeError('Existing result belongs to another protocol or session; no reuse')
            continue # Retain prior session, including failures; never content retry.
        if folder.exists():raise RuntimeError('Partial session requires manual reconciliation; no implicit retry')
        folder.mkdir(parents=True);method=s['method_id']
        if method not in engines:engines[method]=GraphEngine(method) if method=='graph' else TextEngine(method)
        class Backend:
            calls=0
            def search(self,query,limit):
                slots,trace=engines[method].query(query)
                save(folder/'retrieval_traces'/(str(self.calls).zfill(2)+'.json'),dict(query=query,trace=trace));self.calls+=1
                return SlotsBackend(slots).search(query,limit)
        tools=KnowledgeToolSession('bm25',corpus,Backend(),KnowledgeBudget(**cfg['knowledge_budget']))
        client=PaidClient(cfg,out,folder/'requests',count_actual)
        def prepared_client(body,turn):return client({**body,'messages':transformed(body['messages'])},turn)
        result=AutonomousKnowledgeAgent(cfg['logical_model'],tools,prepared_client,count,ModelBudget(**cfg['model_budget'])).run(qmap[s['question_id']])
        result.update(id=s['question_id'],arm=method,session_id=s['session_id'],actual_api_model=cfg['api_model_id'],
            protocol_sha256=cfg['_protocol_sha256'],question_sha256=hashlib.sha256(qmap[s['question_id']].encode()).hexdigest(),
            split_freeze_sha256=cfg['split_freeze_sha256'],
            delivered_lines=[dict(path=p,line=n) for p,n in sorted(tools.delivered_lines)])
        save(result_path,result)
        if result['status'] in bad:raise RuntimeError('Batch stopped after retained infrastructure/budget failure: '+result['status'])
    save(out/'generation_completion.json',dict(sessions=120,protocol_sha256=cfg['_protocol_sha256'],split_freeze_sha256=cfg['split_freeze_sha256'],
        results={s['session_id']:sha(out/s['result_path']) for s in plan['sessions']}))


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',type=Path,required=True)
    mode=p.add_mutually_exclusive_group();mode.add_argument('--dry-run',action='store_true');mode.add_argument('--execute',action='store_true');mode.add_argument('--retrieval-check',choices=['graph','bm25','bge_m3'])
    p.add_argument('--approval',type=Path);a=p.parse_args()
    if not a.execute:offline_guard()
    cfg,root,out,qs,plan=preflight(a.config)
    if a.execute:
        paid_gate(cfg,a.config,a.approval)
        cfg['_protocol_sha256']=sha(a.config)
        lock=out/'execution.lock'
        with lock.open('x',encoding='utf-8') as f:f.write(str(os.getpid()))
        try:execute(cfg,root,out,qs,plan)
        finally:lock.unlink()
    elif a.retrieval_check:
        _,GraphEngine,TextEngine,_=runtime(cfg,root,out);method=a.retrieval_check
        engine=GraphEngine(method) if method=='graph' else TextEngine(method)
        slots,trace=engine.query('blastFoam pressure initialization')
        print(json.dumps(dict(status='offline_retrieval_passed',method=method,slots=len(slots),graph_loaded=trace.get('graph_loaded'),api_calls=0)))
    else:print(json.dumps(dict(status='offline_preflight_passed',sessions=len(plan['sessions']),test_sessions=0,api_calls=0,paid_authorized=False)))


if __name__=='__main__':main()
