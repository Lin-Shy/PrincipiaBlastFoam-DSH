"""Synthetic-only live protocol validation, never formal questions or Gold.

Each invocation creates a new immutable technical run. It is not a retry of a
formal task. Keep failures as evidence; no repair or content retry is performed.
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.request import Request
import argparse,json,re
from models import *
from runtime import run_question
from tokenization import ChatCounter
from principia_core.retrieval.knowledge_qa import FrozenKnowledgeCorpus,KnowledgeBudget,KnowledgeToolSession

def fixture(root):
    folder=root/'synthetic_corpus';(folder/'manual').mkdir(parents=True)
    rows=[]
    for name,text in [('alpha','Synthetic interface fixture, not a blastFoam fact.\nalpha_value = 164\n'),('beta','Synthetic interface fixture, not a blastFoam fact.\nbeta_value = 283\n')]:
        p=folder/'manual'/f'{name}.md';p.write_text(text,'utf-8');raw=p.read_bytes()
        rows.append(dict(path=f'manual/{name}.md',sha256=sha(raw),bytes=len(raw),lines=2))
    manifest=root/'synthetic_manifest.json';manifest.write_bytes(encoded(dict(schema='independent_blast_knowledge_corpus_v1',files=rows)))
    return FrozenKnowledgeCorpus(folder,manifest)

def checks(model,root,corpus):
    d=load_model(model);client=Client(d);counter=ChatCounter(model);folder=root/model;folder.mkdir()
    token_checks=[]
    if model!='qwen3-14b':
        for i,messages in enumerate([
            [dict(role='user',content='中文 synthetic JSON {"x":3}, FINAL:A')],
            [dict(role='system',content='合成分词验证。'),dict(role='user',content='读取alpha。'),dict(role='assistant',content='{"action":"tool","name":"read_source","arguments":{"path":"manual/alpha.md","start":1,"end":2}}'),dict(role='user',content='工具返回：value=164。')],
            [dict(role='system',content='合成分词验证。'),dict(role='user',content='x\n'*500),dict(role='system',content='本轮只返回JSON。')]
        ]):
            body=payload(d,messages,2048);request=dict(model=d.model,messages=body['messages'],add_generation_prompt=True)
            u=d.endpoint.rsplit('/v1/',1)[0]+'/tokenize'
            req=Request(u,data=encoded(request),headers={'Authorization':'Bearer '+d.key,'Content-Type':'application/json'})
            try:
                with client.opener.open(req,timeout=45) as r:value=json.load(r)
                ids=counter.ids(body['messages'])
                row=dict(case=i,request=request,response=value,local_token_ids_sha256=sha(encoded(ids)),
                         exact_ids_match=ids==value.get('tokens'),count_match=len(ids)==value.get('count'),max_model_len=value.get('max_model_len'))
            except Exception as exc:row=dict(case=i,error_type=type(exc).__name__,exact_ids_match=False,count_match=False)
            (folder/f'tokenize_{i}.json').write_bytes(encoded(row));token_checks.append({k:v for k,v in row.items() if k not in {'request','response'}})
    class Backend:
        def search(self,query,limit):return [dict(path=f'manual/{x}.md',start=1,end=2) for x in ('alpha','beta')]
    results=[]
    configs=[(part,mode,'bm25' if mode!='direct' else 'direct') for part in ('open','objective') for mode in ('direct','single_pass','agentic')]+[('open','agentic','basic')]
    for part,mode,method in configs:
        if client.halted.is_set():break
        name=f'{part}_{mode}_{method}';dest=folder/name
        budget=KnowledgeBudget(tool_calls=12,tool_characters=6000,total_characters=12000)
        if mode=='direct':tools=KnowledgeToolSession('none',budget=budget)
        elif method=='basic':
            from chapter2_basic_search_tools import BasicSearchSession
            tools=BasicSearchSession(corpus,budget)
        else:tools=KnowledgeToolSession('bm25',corpus=corpus,backend=Backend(),budget=budget)
        text='这是合成接口核验，不是正式评测。19加23是多少？回答最后一行写FINAL:42。' if mode=='direct' else '这是合成接口核验，不是正式评测。请求alpha与beta核验值之和，回答最后一行写FINAL:总和。'
        if mode=='agentic':text+='先调用read_source读取manual/alpha.md第1到2行，再另一次调用read_source读取manual/beta.md第1到2行；两次分别读取后才回答。'
        q=dict(id='synthetic_'+name,question=text)
        if part=='objective':q['type']='fill'
        result=run_question(q,mode,method,None if mode=='direct' else 'M',tools,client,d,counter,dest/'requests')
        expected='42' if mode=='direct' else '447'
        valid=result['status']=='answered' and (result.get('final_answer')==expected if part=='objective' else re.search(r'(?<!\d)'+expected+r'(?!\d)',result.get('answer') or '') is not None)
        multi=mode!='agentic' or len(tools.events)>=2 and len(result['turns'])>=3
        tokens_match=all(t.get('provider_input_tokens')==t['counted_input_tokens'] for t in result['turns'])
        checked=dict(part=part,mode=mode,method=method,status=result['status'],answer_check=valid,multi_turn_check=multi,
                     tool_calls=len(tools.events),requests=len(result['turns']),
                     passed=result['status']=='answered' and multi and tokens_match,
                     prompt_tokens_match=tokens_match)
        dest.mkdir(parents=True,exist_ok=True);(dest/'result.json').write_bytes(encoded(dict(synthetic_only=True,question=q,**result,checks=checked)))
        results.append(checked)
        print(json.dumps(dict(model=model,**checked)),flush=True)
    report=dict(deployment=public_deployment(d),tokenizer=counter.public(),tokenization_checks=token_checks,results=results,
                passed=len(results)==7 and all(r['passed'] and r['prompt_tokens_match'] for r in results) and all(r['exact_ids_match'] for r in token_checks))
    (folder/'summary.json').write_bytes(encoded(report));return report

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--run-id',required=True);a=parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',a.run_id):raise ValueError('Simple run ID required')
    root=EXPERIMENT/'technical'/a.run_id;root.mkdir(parents=True,exist_ok=False)
    corpus=fixture(root)
    with ThreadPoolExecutor(max_workers=3) as pool:reports=list(pool.map(lambda m:checks(m,root,corpus),MODELS))
    report=dict(schema='synthetic_interface_validation_v1',created_utc=now(),synthetic_only=True,formal_questions_used=0,gold_used=False,
        formal_generation_started=False,models={r['deployment']['logical_model']:r['passed'] for r in reports},
        model_requests=sum(x['requests'] for r in reports for x in r['results']),tokenization_requests=sum(len(r['tokenization_checks']) for r in reports),
        passed=all(r['passed'] for r in reports),implementation_sha256=sha(Path(__file__).read_bytes()))
    (root/'summary.json').write_bytes(encoded(report));print(json.dumps(report),flush=True)

if __name__=='__main__':main()
