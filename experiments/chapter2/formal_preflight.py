"""Synthetic live preflight and immutable readiness receipt for the full run."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
import argparse
import json
from models import MODELS,load_model,encoded,now,sha
from tokenization import ChatCounter
from transport_retry import RetryingClient,RetryPolicy
from runtime import run_question
from technical_checks import fixture
from principia_core.retrieval.knowledge_qa import KnowledgeToolSession,KnowledgeBudget
import formal_experiment as full


def generation_probe(model,root,corpus):
    d=load_model(model);counter=ChatCounter(model);rows=[]
    class Backend:
        def search(self,query,limit):return [dict(path=f'manual/{name}.md',start=1,end=2) for name in ('alpha','beta')]
    for mode in ('single_pass','agentic'):
        tools=KnowledgeToolSession('bm25',corpus=corpus,backend=Backend(),budget=KnowledgeBudget(tool_calls=12,tool_characters=6000,total_characters=12000))
        q=dict(id='synthetic_preflight_'+mode,question='合成接口核验，不是领域知识题。读取manual/alpha.md和manual/beta.md，回答其中alpha_value与beta_value的和。'+('先后分别read_source两份原文，再提交回答。' if mode=='agentic' else ''),type='fill')
        client=RetryingClient(d,RetryPolicy(),concurrency=1)
        folder=root/model/mode
        value=run_question(q,mode,'bm25','M',tools,client,d,counter,folder/'requests')
        requests=[full.read(p) for p in sorted(folder.glob('requests/*.json'))]
        interfaces=[]
        for request,turn in zip(requests,value['turns']):
            raw=request.get('raw_response');interfaces.append(bool(raw and raw['model']==d.model and raw['usage']['prompt_tokens']==turn['counted_input_tokens'] and raw['usage']['completion_tokens']<=2048 and raw['usage']['prompt_tokens']+2048<=32768))
        passed=len(interfaces)>0 and all(interfaces) and value['status'] not in full.UNKNOWN|full.FATAL
        row=dict(model=model,mode=mode,status=value['status'],requests=len(requests),tool_calls=len(tools.events),
                 answer_probe_correct=value.get('final_answer')=='447',interface_passed=passed,
                 interpretation='Content/action failures retained as model outcomes; identity, exact tokenizer accounting and transport are readiness checks')
        full.new(folder/'result.json',dict(synthetic_only=True,**value,checks=row));rows.append(row)
    return dict(model=model,passed=all(r['interface_passed'] for r in rows),cases=rows)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--run-id',required=True);args=parser.parse_args()
    full.require(args.run_id.replace('_','').replace('-','').isalnum(),'Simple run ID required')
    ph,p,frozen,out=full.verify()
    root=full.EXPERIMENT/'technical'/args.run_id;root.mkdir(parents=True,exist_ok=False);corpus=fixture(root)
    with ThreadPoolExecutor(max_workers=3) as pool:models=list(pool.map(lambda m:generation_probe(m,root,corpus),MODELS))
    packet=dict(schema_version='ch2_five_level_dual_eas',sample_id='synthetic_preflight',question='合成资料中的alpha值是多少？',answer='alpha值是164。',generation_failed=False,conditional=False,
                criteria=[dict(criterion_id='synthetic.K1',claim='alpha值为164',evidence_ids=['synthetic'])],sources=[dict(evidence_id='synthetic',path='synthetic_only.md',file_sha256=sha(b'alpha=164'),line_start=1,line_end=1,excerpt='alpha=164',excerpt_sha256=sha(b'alpha=164'))],
                applicability={},acceptable_answer_range=[],critical_errors=[])
    # Explicitly synthetic packet: no formal question, answer, Gold or human score.
    def judge_probe(j):
        result=full.judge_one(ph,{},dict(status='answered',answer=packet['answer']),packet,j,full.judge_profile(j),root/'judges'/j)
        return dict(judge=j,status=result['status'],passed=result['status']=='complete')
    with ThreadPoolExecutor(max_workers=2) as pool:judges=list(pool.map(judge_probe,full.JUDGES))
    receipt=dict(schema='formal_full_preflight_v1',protocol_sha256=ph,checked_utc=now(),synthetic_only=True,formal_questions_used=0,
                 model_checks=models,judge_checks=judges,passed=all(r['passed'] for r in models+judges),
                 offline_checks=full.read(full.EXPERIMENT/'release/validation/formal_offline_checks.json'),
                 acceptance_cancelled=True,human_reference_unchanged=True)
    receipt['passed']=receipt['passed'] and receipt['offline_checks']['passed']
    full.new(root/'summary.json',receipt)
    if receipt['passed']:full.new(frozen/'preflight.json',receipt)
    print(json.dumps(receipt,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
