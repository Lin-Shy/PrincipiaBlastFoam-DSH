"""Matched small local QA diagnosis on public questions; no scoring/gold access."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path
import sys
from threading import RLock
import time

from chapter2_optimization_200 import PROJECT, DATASET, RESOURCES, read, save, sha, snapshot, engine
sys.path.insert(0,str(PROJECT/'src'))
from principia_core.retrieval.knowledge_agent import AutonomousKnowledgeAgent, ModelBudget, SYSTEM
from principia_core.retrieval.knowledge_qa import FrozenKnowledgeCorpus, KnowledgeToolSession, KnowledgeBudget
from chapter2_common_qa_interface import NeutralToolClient, neutral_messages
from chapter2_qa_deployment import DeploymentResponse, token_counter, ANSWER_CHECKLIST
from chapter2_qwen_routing import routed_client

def prepare(a):
    if a.output.exists():raise FileExistsError('New immutable diagnostic required')
    from chapter2_knowledge_input_guard import install
    guard=install(DATASET/'model/questions.json')
    qs=read(DATASET/'model/questions.json')
    selected=qs[::25]
    if len(selected)!=8:raise ValueError('Expected predeclared uniform public-order selection')
    bindings=snapshot(a.output)
    files=[Path(__file__),*(Path(__file__).parent/name for name in [
        'chapter2_common_qa_interface.py','chapter2_qa_deployment.py','chapter2_qwen_routing.py',
        'chapter2_qwen_proxy_config.py','chapter2_qwen_local.py','chapter2_autonomous_qa.py'])]
    for p in files:
        name=p.relative_to(PROJECT).as_posix();bindings[name]=sha(p)
        target=a.output/'runtime'/name
        if not target.exists():
            target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(p.read_bytes())
    save(a.output/'public-questions.json',selected)
    save(a.output/'protocol.json',dict(schema='matched_local_qa_optimization_v1',formal_result=False,
        question_ids=[q['id'] for q in selected],selection='Public array indices 0,25,...,175; no outcomes or scoring labels used',
        questions_sha256=sha(DATASET/'model/questions.json'),selected_sha256=sha(a.output/'public-questions.json'),
        methods=['v4_full','v5_adaptive'],graphs={'v4_full':str(RESOURCES/'graphs/full.json'),'v5_adaptive':str(a.graph.resolve())},
        graph_sha256={'v4_full':sha(RESOURCES/'graphs/full.json'),'v5_adaptive':sha(a.graph)},
        model='qwen3-8b',workload='small',workers=2,model_budget=asdict(ModelBudget()),knowledge_budget=asdict(KnowledgeBudget()),
        tokenizer_binding_sha256=sha(RESOURCES/'tokenizers/qwen3-8b/artifact-binding.json'),system_prompt=SYSTEM,
        common_answer_checklist=ANSWER_CHECKLIST,neutral_tool_description=True,
        implementation_sha256=bindings,input_guard=guard,max_transport_attempts=1,content_retries=0,
        boundary='Internal diagnostic only; unscored and not a full-bank answer-quality comparison'))
    print('Prepared 16 local diagnostic sessions')

def run(a):
    protocol=read(a.output/'protocol.json')
    for name,digest in protocol['implementation_sha256'].items():
        if sha(PROJECT/name)!=digest:raise ValueError('Diagnostic implementation drift: '+name)
    if sha(a.output/'public-questions.json')!=protocol['selected_sha256']:raise ValueError('Selected question drift')
    for method,path in protocol['graphs'].items():
        if sha(path)!=protocol['graph_sha256'][method]:raise ValueError('Diagnostic graph drift')
    from chapter2_autonomous_qa import load_tokenizer
    raw,binding=load_tokenizer(RESOURCES/'tokenizers/qwen3-8b','qwen3-8b')
    lock=RLock()
    def count(messages):
        with lock:return raw(neutral_messages(messages))
    counter=token_counter(count,'small',ANSWER_CHECKLIST)
    from chapter2_knowledge_input_guard import install
    install(DATASET/'model/questions.json')
    corpus=FrozenKnowledgeCorpus(RESOURCES/'corpus',RESOURCES/'corpus-manifest.json')
    backends={m:engine(m,Path(protocol['graphs'][m])) for m in protocol['methods']}
    qs=read(a.output/'public-questions.json')
    jobs=[(q,m) for q in qs for m in protocol['methods']]
    def worker(q,method):
        folder=a.output/'sessions'/method/q['id']
        if (folder/'result.json').exists():return read(folder/'result.json')['status']
        if (folder/'requests').exists():raise ValueError('Unresolved diagnostic cannot be silently reissued')
        client=DeploymentResponse(NeutralToolClient(routed_client('qwen3-8b',folder/'requests',workload='small',timeout=120)),
            'qwen3-8b',ANSWER_CHECKLIST)
        tools=KnowledgeToolSession('graph',corpus,backends[method],KnowledgeBudget())
        started=time.monotonic()
        result=AutonomousKnowledgeAgent('qwen3-8b',tools,client,counter,ModelBudget()).run(q['question'])
        result.update(id=q['id'],method=method,formal_result=False,workload='small',seconds=time.monotonic()-started,
            protocol_sha256=sha(a.output/'protocol.json'))
        save(folder/'result.json',result)
        print(q['id'],method,result['status'],flush=True)
        return result['status']
    counts=Counter()
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures=[pool.submit(worker,q,m) for q,m in jobs]
        for f in as_completed(futures):counts[f.result()]+=1
    save(a.output/'completion.json',dict(sessions=len(jobs),statuses=dict(counts),formal_result=False,
        provider='qwen_local',model='Qwen3-8B',scored=False,protocol_sha256=sha(a.output/'protocol.json')))
    print(dict(counts))

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['prepare','run'])
    p.add_argument('--graph',type=Path);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();(prepare if a.command=='prepare' else run)(a)
if __name__=='__main__':main()
