"""Close undeliverable Unicode outputs locally, with zero new model requests."""
from collections import Counter
from copy import deepcopy
from datetime import datetime
import json
import os
from pathlib import Path
from types import SimpleNamespace
from chapter2_optimization_200 import PROJECT, DATASET, RESOURCES, read, sha, engine
from chapter2_model14b_200 import ARMS, PROFILES, MODEL
from chapter2_selected_graph_200 import backend
from chapter2_autonomous_qa import load_tokenizer
from chapter2_common_qa_interface import NeutralToolClient, neutral_messages
from chapter2_qa_deployment import DeploymentResponse, token_counter, ANSWER_CHECKLIST
from chapter2_publication_200 import verify
from principia_core.retrieval.knowledge_agent import AutonomousKnowledgeAgent, ModelBudget
from principia_core.retrieval.knowledge_qa import FrozenKnowledgeCorpus, KnowledgeToolSession, KnowledgeBudget

ROOT=PROJECT.parent/'graduation-experiment-results/chapter2_retrieval/current/model14b_200_20261019_002'


def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf-8') as stream:
        json.dump(value,stream,ensure_ascii=True,indent=2)


def main():
    p=verify(ROOT);questions=read(ROOT/'public-questions.json')
    bad=[]
    for arm in ARMS:
        for q in questions:
            path=ROOT/'generation'/arm/q['id']/'result.json'
            try:read(path)
            except json.JSONDecodeError:bad.append((arm,q,path))
    if len(bad)!=2 or {arm for arm,_,_ in bad}!={'graph','hybrid'}:
        raise ValueError('Only the two recorded Unicode serialization failures may be closed')
    counter,_=load_tokenizer(RESOURCES/'tokenizers/qwen3-14b',MODEL)
    corpus=FrozenKnowledgeCorpus(RESOURCES/'corpus',RESOURCES/'corpus-manifest.json')
    records=[]
    for arm,q,path in bad:
        receipts=[read(f) for f in sorted((path.parent/'requests').glob('*.json'))]
        class Replay:
            deployment=SimpleNamespace(model=MODEL)
            calls=0
            def __call__(self,body,turn):
                receipt=receipts[turn]
                if receipt['request']!=body:
                    raise ValueError('Frozen replay request differs')
                self.calls+=1
                return deepcopy(receipt)
        if arm=='graph':selected=backend(ROOT/'graphs',PROFILES[arm])
        else:
            os.environ['HF_HUB_CACHE']=read(RESOURCES/'e5/runtime-spec.json')['cache_folder']
            os.environ['HF_HUB_OFFLINE']='1';os.environ['TRANSFORMERS_OFFLINE']='1'
            selected=engine(arm,None)
        replay=Replay()
        client=DeploymentResponse(NeutralToolClient(replay),MODEL,ANSWER_CHECKLIST)
        tools=KnowledgeToolSession('graph' if arm=='graph' else arm,corpus,selected,KnowledgeBudget(**p['knowledge_budget']))
        count=token_counter(lambda m:counter(neutral_messages(m)),'bulk',ANSWER_CHECKLIST)
        value=AutonomousKnowledgeAgent(MODEL,tools,client,count,ModelBudget(**p['model_budget'])).run(q['question'])
        assert replay.calls==len(receipts) and value['status']=='answered'
        try:value['answer'].encode('utf-8')
        except UnicodeEncodeError:pass
        else:raise ValueError('This is not the observed undeliverable Unicode answer')
        preserved=ROOT/'recovery'/arm/(q['id']+'-consumer-result.json')
        write(preserved,value)
        saved=path.with_name('result.serialization-failed.bin')
        assert path.resolve().is_relative_to(ROOT.resolve()) and saved.resolve().is_relative_to(ROOT.resolve())
        path.rename(saved)
        starts=[datetime.fromisoformat(r['started_utc']).timestamp() for r in receipts]
        request_span=max(t+r['seconds'] for t,r in zip(starts,receipts))-min(starts)
        value.update(status='invalid_unicode_output',consumer_terminal_status='answered',
            answer='',references=[],references_delivered=None,
            id=q['id'],arm=arm,answer_model=MODEL,protocol_sha256=sha(ROOT/'protocol.json'),
            delivered_lines=[dict(path=f,line=n) for f,n in sorted(tools.delivered_lines)],
            seconds=request_span,timing_scope='Recorded request interval span only; original host total was not serialized',
            timing_lower_bound=True,delivery_failure='Unpaired Unicode surrogate in final answer; no text repair or new request',
            undeliverable_consumer_result_sha256=sha(preserved))
        write(path,value)
        records.append(dict(arm=arm,id=q['id'],partial_bytes_sha256=sha(saved),
            preserved_consumer_result_sha256=sha(preserved),closed_result_sha256=sha(path),
            requests_before_and_after=len(receipts),network_calls_during_closure=0,
            timing_measurement='Request interval span is a lower bound, not the unavailable original host timer'))
    for arm in ARMS:
        target=ROOT/'completion'/(arm+'.json')
        if target.exists():continue
        values=[read(ROOT/'generation'/arm/q['id']/'result.json') for q in questions]
        write(target,dict(arm=arm,sessions=200,statuses=dict(Counter(v['status'] for v in values)),
            protocol_sha256=sha(ROOT/'protocol.json'),
            results_sha256={q['id']:sha(ROOT/'generation'/arm/q['id']/'result.json') for q in questions},
            local_unicode_delivery_closure=True))
    control=read(ROOT/'generation-controller-completion.json')
    write(ROOT/'recovery/original-generation-controller.json',control)
    control.update(complete=True,completion_scope='All 1400 terminal records accounted; original exit codes retained',
        local_unicode_delivery_failures=2,new_network_requests=0)
    (ROOT/'generation-controller-completion.json').write_text(json.dumps(control,indent=2)+'\n',encoding='utf-8')
    write(ROOT/'recovery/closure.json',dict(source_sha256=sha(Path(__file__)),recovered_sessions=records,
        network_calls=0,answer_text_repairs=0,semantic_scoring_of_these_failures=False,
        rule='No valid UTF-8 final answer delivered: retain as generation failure with zero score; preserve raw receipts and decoded consumer result'))
    print(json.dumps(dict(closed=1400,invalid_unicode_failures=2,new_requests=0)))


if __name__=='__main__':main()
