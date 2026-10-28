"""Frozen Test160 runner. Offline check is default; execution needs owner matrix confirmation.

No Test answer/score is read during preparation. No Test API request is authorized
by this source file or by the current Dev40 task.
"""
import runtime_layout as layout
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import threading

import single_pass_dev40 as s
from central_execution import Registry,exclusive_lock

ROOT=s.RUN/'release/validation'
MANIFEST=layout.asset('test_manifest')
LOCK=threading.RLock()


def load_frozen(path=MANIFEST):
    m=s.load(path)
    if m['scope']!=dict(models=2,methods=13,questions=160,sessions=4160):
        raise ValueError('Unexpected Test scope')
    for rel,expected in m['bindings'].items():
        if s.sha(s.WORKSPACE/rel)!=expected:raise ValueError('Frozen binding drift: '+rel)
    questions=s.load(s.WORKSPACE/m['question_file'])
    if len(questions)!=160 or any(set(q)!={'id','question'} for q in questions):
        raise ValueError('Test inputs must contain id/question only')
    if len({q['id'] for q in questions})!=160:raise ValueError('Duplicate question')
    assert not ({q['id'] for q in questions}&{q['id'] for q in s.load(s.QUESTIONS)})
    configs=m['configurations']
    if len(configs)!=26 or len({c['config_id'] for c in configs})!=26:raise ValueError('Invalid config count')
    registry=Registry()
    for c in configs:
        route=registry.resolve(c['model_key'])
        if route!=m['deployments'][c['model_key']]:raise ValueError('Deployment configuration changed')
    return m,questions


def runtime(m):
    common=s.paths_and_runtime()
    common.QUESTIONS=s.WORKSPACE/m['question_file']
    from retrieval import GraphEngine,TextEngine
    from dev40_retrieval_study import FilteredGraph
    from principia_core.retrieval.knowledge_qa import FrozenKnowledgeCorpus,KnowledgeToolSession,KnowledgeBudget,tool_specs
    from chapter2_basic_search_tools import BasicSearchSession,basic_specs
    import principia_core.retrieval.knowledge_agent as agent
    original_specs=agent.tool_specs
    agent.tool_specs=lambda method:basic_specs() if method=='basic_search' else original_specs(method)
    corpus=FrozenKnowledgeCorpus(common.RESOURCES/'corpus',common.RESOURCES/'corpus-manifest.json')
    engines={}
    def engine(c):
        method=c['method_id'];key=(method,c.get('top_slots'))
        with LOCK:
            if key not in engines:
                if method=='graph' and c.get('top_slots',10)!=10:
                    engines[key]=FilteredGraph({'top_slots':c['top_slots']})
                elif method in ('graph','no_cross','no_aliases','no_traversal','anchor_only'):
                    engines[key]=GraphEngine(method)
                else:engines[key]=TextEngine(method)
            return engines[key]
    def tools(c,folder):
        method=c['method_id']
        p=c['candidate_parameters']
        budget=KnowledgeBudget(p['tool_calls'],p['one_characters'],p['total_characters']) if p else KnowledgeBudget()
        if method=='direct':return KnowledgeToolSession('none')
        if method=='basic':return BasicSearchSession(corpus,budget)
        from retrieval import SlotsBackend
        class Backend:
            calls=0
            def search(self,query,limit):
                with LOCK:slots,trace=engine(c).query(query)
                if folder is not None:s.save(folder/'retrieval_traces'/(str(self.calls).zfill(2)+'.json'),dict(query=query,trace=trace))
                self.calls+=1
                return SlotsBackend(slots).search(query,limit)
        return KnowledgeToolSession('bm25',corpus,Backend(),budget)
    return tools,engine,corpus


def check():
    m,questions=load_frozen()
    os.environ.update(HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',TOKENIZERS_PARALLELISM='false')
    # After data/Gold hashes have been verified, prohibit evaluation reads and all network.
    opened=[]
    def guard(event,args):
        if event in ('socket.connect','socket.connect_ex','socket.getaddrinfo'):
            raise PermissionError('Offline Test160 preflight cannot send requests')
        if event=='open' and args and isinstance(args[0],(str,bytes,os.PathLike)):
            p=os.fsdecode(args[0]).replace('\\','/')
            if '/test160_runs/' in p or '/data/gold/test160/' in p:
                raise PermissionError('Test results and Test Gold are not generation inputs')
            opened.append(p)
    sys.addaudithook(guard)
    make_tools,engine,corpus=runtime(m)
    from principia_core.retrieval.knowledge_qa import tool_specs
    from chapter2_basic_search_tools import basic_specs
    # Smoke retrieval uses a Dev question, never a Test query for development.
    q=s.load(s.QUESTIONS)[0]
    checks=[]
    tested={}
    for c in m['configurations']:
        method=c['method_id'];session=make_tools(c,None)
        specs=basic_specs() if method=='basic' else tool_specs(session.method)
        if method=='direct':assert not specs
        elif method=='basic':assert {z['name'] for z in specs}=={'glob','grep','read_source'}
        else:
            assert {'catalog','read_source','search'}=={z['name'] for z in specs}
            if method not in tested:
                delivery=session.execute('search',{'query':q['question']})
                assert len(delivery)<=c['candidate_parameters']['one_characters']
                assert session.events[0]['status']=='returned'
                tested[method]=dict(characters=len(delivery),lines=len(session.delivered_lines))
        checks.append(dict(config_id=c['config_id'],tools=[z['name'] for z in specs],
                           protocol_loaded=True,backend_check=tested.get(method)))
    result=dict(checked_utc=s.now(),manifest_sha256=s.sha(MANIFEST),questions_loaded=160,
                configurations_loaded=26,sessions=4160,checks=checks,network_requests=0,
                test_queries_used_for_development=0,test_answers_read=0,test_scores_read=0,
                test_gold_used_for_generation=False,resume='Existing result => skip; request without result => unknown_hold, never resend',
                status='offline_ready',test160_started=False,owner_confirmation_pending=True)
    s.save(ROOT/'test160_preflight.json',result)
    print(json.dumps({k:v for k,v in result.items() if k!='checks'},ensure_ascii=False),flush=True)


def execute(authorization):
    # This gate is checked before loading a production runtime or any API key.
    if authorization is None:raise PermissionError('Owner has not confirmed the final Test160 matrix')
    approved=s.load(authorization)
    if approved.get('owner_confirmed') is not True or approved.get('manifest_sha256')!=s.sha(MANIFEST):
        raise PermissionError('Approval must bind this exact final Test160 manifest')
    m,questions=load_frozen()
    output=s.RUN/'test160_runs';output.mkdir(exist_ok=True)
    registry=Registry()
    make_tools,engine,corpus=runtime(m)
    import dev40_supplement as transport
    transport.ROOT=output
    from principia_core.retrieval.knowledge_agent import AutonomousKnowledgeAgent,ModelBudget
    from transformers import AutoTokenizer
    from chapter2_common_qa_interface import neutral_messages
    from chapter2_qa_deployment import prepared_messages,ANSWER_CHECKLIST
    common=sys.modules['common']
    tokenizer=AutoTokenizer.from_pretrained(str(common.RESOURCES/'tokenizers/qwen3-14b'),local_files_only=True,trust_remote_code=False)
    def count(messages):
        with LOCK:return len(tokenizer.apply_chat_template(messages,tokenize=True,add_generation_prompt=True,enable_thinking=False))
    def job(c,q):
        folder=output/'generation'/c['config_id']/q['id']
        if (folder/'result.json').exists():return 'existing_terminal_result'
        if (folder/'requests').exists():return 'unknown_hold'
        folder.mkdir(parents=True,exist_ok=True)
        tools=make_tools(c,folder);raw_client=transport.client(folder,c['logical_model'])
        route=registry.resolve(c['model_key'])
        def transform(messages):
            result=prepared_messages(messages,ANSWER_CHECKLIST)
            if c['method_id']!='basic':result=neutral_messages(result)
            if route.get('append_last_user_suffix'):
                for msg in reversed(result):
                    if msg['role']=='user':msg['content']+='\n'+route['append_last_user_suffix'];break
            return result
        def client(body,turn):
            payload=deepcopy(body);payload['messages']=transform(body['messages'])
            if count(payload['messages'])+payload['max_tokens']>32768:return dict(status='combined_context_budget_exhausted')
            return raw_client(payload,turn)
        result=AutonomousKnowledgeAgent(c['logical_model'],tools,client,lambda z:count(transform(z)),ModelBudget(input_tokens_per_request=30720)).run(q['question'])
        result.update(id=q['id'],arm=c['method_id'],config_id=c['config_id'],
            manifest_sha256=s.sha(MANIFEST),question_sha256=hashlib.sha256(q['question'].encode()).hexdigest(),
            delivered_lines=[dict(path=p,line=n) for p,n in sorted(tools.delivered_lines)])
        s.save(folder/'result.json',result)
        return result['status']
    import hashlib
    with exclusive_lock(output/'generation.lock'):
        def lane(model):
            jobs=[(c,q) for c in m['configurations'] if c['model_key']==model for q in questions]
            with ThreadPoolExecutor(max_workers=8 if model=='qwen3_8b' else 20) as pool:
                for state in pool.map(lambda z:job(*z),jobs):print(json.dumps(dict(model=model,status=state)),flush=True)
        with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(lane,['qwen3_8b','qwen3_14b']))


def execute_single_pass(authorization):
    if authorization is None:raise PermissionError('Owner has not confirmed the supplementary matrix')
    approved=s.load(authorization)
    if (approved.get('owner_confirmed') is not True or approved.get('manifest_sha256')!=s.sha(MANIFEST)
        or 'single_pass_3' not in approved.get('approved_supplements',[])):
        raise PermissionError('Single-Pass supplement requires explicit inclusion in the matrix confirmation')
    m,questions=load_frozen()
    output=s.RUN/'test160_runs/supplement/single_pass';output.mkdir(parents=True,exist_ok=True)
    make_tools,engine,corpus=runtime(m)
    import dev40_supplement as transport
    transport.ROOT=output
    common=sys.modules['common']
    configs=[c for c in m['configurations'] if c['method_id'] in ('graph','bm25','bge_m3')]
    prompt_rule=s.load(s.WORKSPACE/m['single_pass_protocol_file'])['generation_prompt']
    def job(c,q):
        folder=output/'generation'/c['config_id']/q['id']
        if (folder/'result.json').exists():return 'existing_terminal_result'
        if (folder/'requests').exists():return 'unknown_hold'
        folder.mkdir(parents=True,exist_ok=True)
        evidence,event=s.retrieve(c['method_id'],q['question'],common,engine(c),folder)
        prompt='Question:\n'+q['question']+'\n\nRetrieved original-source evidence (JSON, including paths and line numbers):\n'+evidence+'\n\n'+prompt_rule
        if c['model_key']=='qwen3_8b':prompt+='\n/no_think'
        body=dict(model=c['logical_model'],messages=[dict(role='user',content=prompt)],temperature=0,max_tokens=2048,enable_thinking=False,stream=False)
        response=transport.client(folder,c['logical_model'])(body,0)
        raw=response.get('raw_response',{});choices=raw.get('choices',[])
        answer=choices[0].get('message',{}).get('content') if choices else None
        ok=response['status']=='response' and bool(answer) and choices[0].get('finish_reason')=='stop'
        result=dict(id=q['id'],arm=c['method_id'],model=c['logical_model'],config_id=c['config_id'],
            status='answered' if ok else response['status'],answer=answer or '',manifest_sha256=s.sha(MANIFEST),
            delivered_lines=s.load(folder/'retrieval.json')['delivered_lines'],knowledge_characters=len(evidence),
            tool_events=[dict(name='search',status=event.get('status'))],counted_input_tokens=raw.get('usage',{}).get('prompt_tokens'),
            actual_completion_tokens=raw.get('usage',{}).get('completion_tokens'),backend_calls=1,model_tools=[],execution_mode='single_pass')
        s.save(folder/'result.json',result)
        return result['status']
    with exclusive_lock(output/'generation.lock'):
        with ThreadPoolExecutor(max_workers=6) as pool:
            for status in pool.map(lambda z:job(*z),[(c,q) for c in configs for q in questions]):print(status,flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=['check','execute','execute-single-pass'],default='check',nargs='?')
    p.add_argument('--authorization',type=Path);a=p.parse_args()
    if a.command=='check':check()
    elif a.command=='execute':execute(a.authorization)
    else:execute_single_pass(a.authorization)
