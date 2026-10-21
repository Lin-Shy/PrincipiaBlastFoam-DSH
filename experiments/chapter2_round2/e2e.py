"""待审批的14B新批次；prepare离线，answer必须有绑定协议的明确批准记录。"""
import argparse
from collections import Counter
import random
from threading import RLock
import time

from common import *

ARMS=['graph','bm25','bge_m3','bm25_bge_m3','bm25_parent','no_traversal','anchor_only']

def prepare():
    from principia_core.retrieval.knowledge_agent import SYSTEM
    from chapter2_qa_deployment import ANSWER_CHECKLIST
    from chapter2_common_qa_interface import SEARCH_DESCRIPTION
    old=read(HISTORICAL/'protocol.json')
    if SYSTEM!=old['system_prompt'] or ANSWER_CHECKLIST!=old['common_answer_checklist'] or SEARCH_DESCRIPTION!=old['common_search_description']:
        raise ValueError('historical prompt drift')
    index=ARCHIVE/'indexes/bge_dense_v1/manifest.json'
    if not index.exists():raise ValueError('actual BGE index must be complete before e2e freeze')
    p=dict(schema='round2_e2e14b_v1',status='frozen_pending_user_approval',arms=ARMS,question_count=200,sessions=1400,
        newly_added_sessions=1000,reference_rerun_sessions=400,answer_model='qwen3-14b',provider='qwen_proxy',workload='bulk',
        temperature=0,enable_thinking=False,max_transport_attempts=1,content_retries=0,max_concurrent_answer_requests=2,
        endpoint=read(HISTORICAL/'user-authorization.json')['endpoint'],
        model_budget=old['model_budget'],knowledge_budget=old['knowledge_budget'],system_prompt=SYSTEM,
        common_answer_checklist=ANSWER_CHECKLIST,common_search_description=SEARCH_DESCRIPTION,
        questions_sha256=sha(QUESTIONS),source_map_sha256=sha(RESOURCES/'source-map.json'),graph_sha256=sha(GRAPH),
        bge_index_sha256=sha(index),bge_model_binding_sha256=sha(ARCHIVE/'indexes/bge_model_binding.json'),
        tokenizer_binding_sha256=sha(RESOURCES/'tokenizers/qwen3-14b/artifact-binding.json'),
        historical_protocol_sha256=sha(HISTORICAL/'protocol.json'),
        retrieval_protocol_sha256=sha(ARCHIVE/'configs/retrieval_v1.json'),
        code={p.name:sha(p) for p in HERE.glob('*.py')},legacy_code=old['implementation_sha256'],
        judge=old['judge'],statistics={**old['statistics'],'comparison_families':{
            'main':['graph vs '+a for a in ['bm25','bge_m3','bm25_bge_m3','bm25_parent']],
            'new_ablations':['graph vs no_traversal','graph vs anchor_only']}},
        old_ablations='historical descriptive results retain original identity; not mixed into new paired confirmatory family',
        reference_reuse='No direct confirmatory reuse: new canonical line dedup and new batch require graph/BM25 paired reruns. Historical results descriptive only.',
        scoring_data_sha256=old['scoring_data_sha256'],
        protocol_boundary='Exposed development bank; adaptive round2, no unseen generalization. Future provider revision cannot be proven identical solely by model string.',
        design_sha256=sha(WORKSPACE/'graduation-thesis-materials/graduation-research/chapters/chapter02.md'),
        paid_scoring='separate approval and frozen scoring execution protocol required; never implicit in generation approval')
    save(ARCHIVE/'configs/e2e_14b_v1.json',p)
    runtime=ARCHIVE/'e2e_runtime_v1';runtime.mkdir(exist_ok=False)
    for name in p['code']:(runtime/name).write_bytes((HERE/name).read_bytes())
    print('e2e frozen pending user approval',sha(ARCHIVE/'configs/e2e_14b_v1.json'))

def approval_check(approval,protocol):
    a=read(approval);p=read(protocol)
    if a.get('approved') is not True or a.get('protocol_sha256')!=sha(protocol) or a.get('scope')!='generation' or a.get('max_sessions',0)<p['sessions'] or not a.get('user_instruction','').strip():
        raise PermissionError('explicit user generation approval bound to exact protocol and scale required')
    return p

def answer(arm,run_id,approval):
    protocol=ARCHIVE/'configs/e2e_14b_v1.json';p=approval_check(approval,protocol)
    if arm not in p['arms']:raise ValueError('unknown arm')
    for name,h in p['code'].items():
        if sha(HERE/name)!=h:raise ValueError('e2e source drift')
    for name,h in p['legacy_code'].items():
        if sha(PROJECT/name)!=h:raise ValueError('historical implementation drift')
    bindings=[(QUESTIONS,p['questions_sha256']),(RESOURCES/'source-map.json',p['source_map_sha256']),
        (ARCHIVE/'indexes/bge_dense_v1/manifest.json',p['bge_index_sha256']),
        (RESOURCES/'tokenizers/qwen3-14b/artifact-binding.json',p['tokenizer_binding_sha256'])]
    if arm in ['graph','no_traversal','anchor_only']:bindings.append((GRAPH,p['graph_sha256']))
    if any(sha(file)!=h for file,h in bindings):raise ValueError('e2e input identity drift')
    # Online guard permits configured LLM client; gold and child processes blocked.
    from chapter2_knowledge_input_guard import install
    install(QUESTIONS)
    from retrieval import GraphEngine,TextEngine,SlotsBackend
    from principia_core.retrieval.knowledge_agent import AutonomousKnowledgeAgent,ModelBudget
    from principia_core.retrieval.knowledge_qa import FrozenKnowledgeCorpus,KnowledgeToolSession,KnowledgeBudget
    from chapter2_autonomous_qa import load_tokenizer
    from chapter2_common_qa_interface import NeutralToolClient,neutral_messages
    from chapter2_qa_deployment import DeploymentResponse,token_counter,ANSWER_CHECKLIST
    from chapter2_qwen_routing import routed_client
    root=ARCHIVE/'e2e_runs'/run_id/arm;root.mkdir(parents=True,exist_ok=False)
    engine=GraphEngine(arm) if arm in ['graph','no_traversal','anchor_only'] else TextEngine(arm)
    raw,_=load_tokenizer(RESOURCES/'tokenizers/qwen3-14b','qwen3-14b')
    counter=token_counter(lambda messages:raw(neutral_messages(messages)),'bulk',ANSWER_CHECKLIST)
    corpus=FrozenKnowledgeCorpus(RESOURCES/'corpus',RESOURCES/'corpus-manifest.json')
    questions=public_questions();random.Random(20261020).shuffle(questions)
    counts=Counter()
    for q in questions:
        folder=root/'generation'/q['id'];folder.mkdir(parents=True,exist_ok=False)
        class Backend:
            calls=0
            def search(self,query,limit):
                rows,trace=engine.query(query)
                save(folder/'retrieval_traces'/f'{self.calls:02d}.json',dict(query=query,trace=trace))
                self.calls+=1
                return SlotsBackend(rows).search(query,limit)
        tools=KnowledgeToolSession('bm25',corpus,Backend(),KnowledgeBudget(**p['knowledge_budget']))
        client=DeploymentResponse(NeutralToolClient(routed_client('qwen3-14b',folder/'requests',workload='bulk',timeout=180)),
            'qwen3-14b',ANSWER_CHECKLIST)
        begin=time.monotonic()
        result=AutonomousKnowledgeAgent('qwen3-14b',tools,client,counter,ModelBudget(**p['model_budget'])).run(q['question'])
        result.update(id=q['id'],arm=arm,answer_model='qwen3-14b',protocol_sha256=sha(protocol),
            seconds=time.monotonic()-begin,delivered_lines=[dict(path=p,line=n) for p,n in sorted(tools.delivered_lines)])
        save(folder/'result.json',result);counts[result['status']]+=1
    save(root/'completed.json',dict(arm=arm,questions=200,statuses=dict(counts),protocol_sha256=sha(protocol),
        results_sha256={q['id']:sha(root/'generation'/q['id']/'result.json') for q in questions}))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['prepare','answer'])
    p.add_argument('--arm',choices=ARMS);p.add_argument('--run-id');p.add_argument('--approval',type=Path)
    a=p.parse_args()
    prepare() if a.action=='prepare' else answer(a.arm,a.run_id,a.approval)
