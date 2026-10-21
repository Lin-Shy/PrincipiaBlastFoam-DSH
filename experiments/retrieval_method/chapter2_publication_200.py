"""Fresh full-200 QA protocol; isolated arm processes, at most 14 proxy calls."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict
import os
from pathlib import Path
import random
from threading import RLock
import subprocess
import sys
import time

from chapter2_optimization_200 import PROJECT, DATASET, RESOURCES, read, save, sha, engine
from chapter2_judge_200 import freeze
sys.path.insert(0,str(PROJECT/'src'))
from principia_core.retrieval.knowledge_agent import AutonomousKnowledgeAgent, ModelBudget, SYSTEM
from principia_core.retrieval.knowledge_qa import FrozenKnowledgeCorpus, KnowledgeToolSession, KnowledgeBudget
from chapter2_common_qa_interface import NeutralToolClient, neutral_messages, SEARCH_DESCRIPTION
from chapter2_qa_deployment import DeploymentResponse, token_counter, ANSWER_CHECKLIST
from chapter2_qwen_routing import routed_client

ARMS = ['graph','bm25','e5','hybrid','none','graph_no_cross','graph_no_conditions']


def prepare(a):
    if a.output.exists(): raise FileExistsError('Fresh full-bank protocol required')
    calibration=read(a.calibration/'completion.json')
    if not calibration['calibration_passed'] or calibration['passed']!=7:
        raise ValueError('All seven new-bank judge controls must pass first')
    calibration_protocol=a.calibration/'protocol.json'
    if calibration['protocol_sha256']!=sha(calibration_protocol): raise ValueError('Calibration drift')
    for cid,digest in calibration['results_sha256'].items():
        if sha(a.calibration/'sessions'/cid/'result.json')!=digest: raise ValueError('Calibration result drift')
    questions=read(DATASET/'model/questions.json')
    if len(questions)!=200 or any(set(q)!={'id','question'} for q in questions): raise ValueError('Exact public bank required')
    bindings=freeze(a.output)
    for name in ['chapter2_publication_200.py','chapter2_knowledge_graph_variants.py','chapter2_qa_deployment.py','chapter2_common_qa_interface.py','chapter2_autonomous_qa.py']:
        source=Path(__file__).with_name(name); rel=source.relative_to(PROJECT).as_posix();bindings[rel]=sha(source)
        target=a.output/'runtime'/rel
        if not target.exists():target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(source.read_bytes())
    from chapter2_knowledge_graph_variants import variant
    graph=read(a.graph)
    for arm,kind in [('graph','full'),('graph_no_cross','no_cross'),('graph_no_conditions','no_conditions')]:
        revised,audit=variant(graph,kind)
        save(a.output/'graphs'/(arm+'.json'),revised);save(a.output/'graphs'/(arm+'-audit.json'),audit)
    save(a.output/'public-questions.json',questions)
    protocol=dict(schema='publication_200_qa_v1',status='frozen_before_generation',seed=20261019,
        question_count=200,arms=ARMS,generation_sessions=1400,answer_model='qwen3-8b',provider='qwen_proxy',workload='bulk',
        workers_per_arm=2,max_concurrent_answer_requests=14,max_transport_attempts=1,content_retries=0,
        questions_sha256=sha(DATASET/'model/questions.json'),public_questions_sha256=sha(a.output/'public-questions.json'),
        dataset_binding_sha256=sha(DATASET/'binding.json'),
        scoring_data_sha256={n:sha(DATASET/'scoring'/n) for n in ['annotations.json','evidence.json']},
        model_budget=asdict(ModelBudget()),knowledge_budget=asdict(KnowledgeBudget()),
        system_prompt=SYSTEM,common_answer_checklist=ANSWER_CHECKLIST,common_search_description=SEARCH_DESCRIPTION,
        consumer='Independent autonomous bounded agent; common neutral tools and prompts; graph/baseline processes isolated',
        graph_selection='v6_unit_aliases_verified; adaptive development on exposed bank, not unseen generalization',
        construction_graph_sha256=sha(a.graph),graphs={arm:sha(a.output/'graphs'/(arm+'.json')) for arm in ['graph','graph_no_cross','graph_no_conditions']},
        graph_method='v6_unit with adaptive original-source context; cross-source and condition ablations match physical artifacts',
        e5_resources={n:sha(RESOURCES/'e5'/n) for n in ['manifest.json','runtime-spec.json','passages.json','embeddings.npy']},
        tokenizer_sha256=sha(RESOURCES/'tokenizers/qwen3-8b/artifact-binding.json'),
        source_resources={n:sha(RESOURCES/n) for n in ['corpus-manifest.json','source-map.json']},
        implementation_sha256=bindings,design_sha256=sha(PROJECT.parent/'graduation-thesis-materials/graduation-research/chapters/chapter02.md'),
        judge=dict(model='qwen3-14b',provider='qwen_proxy',calibration=str(a.calibration.resolve()),
            calibration_protocol_sha256=sha(calibration_protocol),calibration_completion_sha256=sha(a.calibration/'completion.json'),
            rubric='source_free_question_bound_200_v2',max_targeted_reviews_per_answer=0,
            rule='Candidate-only point coverage; independent original truth and condition audit; strict parsing; no content retries or silent repair'),
        statistics=dict(primary='Complete valid delivered answer rate, all 200; necessary point coverage and condition accuracy auxiliary',
            complete='All required points satisfied, no established false substantive claim or unresolved substantive claim, correct condition when required',
            generation_failure='No delivered valid final answer counts 0, including transport/budget/format failure; original status retained',
            judge_unknown='Keep lower/upper bounds; never remove unknowns from denominator',
            question_micro_and_knowledge_group_macro=True,paired_unit='24 pre-existing knowledge groups; cluster paired bootstrap 10000, seed20261019',
            comparison_families=dict(primary=['graph vs '+m for m in ['bm25','e5','hybrid','none']],
                ablation=['graph vs graph_no_cross','graph vs graph_no_conditions']),
            multiplicity='Holm within each predeclared family; paired cluster sign randomization; two-sided',
            practical_difference_percentage_points=5,
            boundary='Same exposed bank as adaptive retrieval development; fixed-benchmark method comparison only, not independent generalization'),
        initial_e5_note='Identical raw Chinese query diagnostic was weak; vector/source consistency verified. Final autonomous consumers may query English. No baseline ranking is replaced or hidden.')
    save(a.output/'protocol.json',protocol)
    print(dict(sessions=1400,model='qwen3-8b',workers=14))


def verify(root):
    protocol=read(root/'protocol.json')
    for name,digest in protocol['implementation_sha256'].items():
        if sha(PROJECT/name)!=digest:raise ValueError('Frozen implementation drift: '+name)
    if sha(root/'public-questions.json')!=protocol['public_questions_sha256']:raise ValueError('Public questions drift')
    for arm,digest in protocol['graphs'].items():
        if sha(root/'graphs'/(arm+'.json'))!=digest:raise ValueError('Graph variant drift')
    for name,digest in protocol['source_resources'].items():
        if sha(RESOURCES/name)!=digest:raise ValueError('Source resource drift')
    return protocol


def answer(a):
    protocol=verify(a.output)
    if a.arm not in ARMS:raise ValueError('Unknown answer arm')
    from chapter2_knowledge_input_guard import install
    install(DATASET/'model/questions.json')
    from chapter2_autonomous_qa import load_tokenizer
    raw,_=load_tokenizer(RESOURCES/'tokenizers/qwen3-8b','qwen3-8b');lock=RLock()
    def count(messages):
        with lock:return raw(neutral_messages(messages))
    counter=token_counter(count,'bulk',ANSWER_CHECKLIST)
    arm=a.arm
    backend=None;corpus=None;method=arm
    if arm!='none':
        corpus=FrozenKnowledgeCorpus(RESOURCES/'corpus',RESOURCES/'corpus-manifest.json')
        if arm.startswith('graph'):
            method='graph';key='v6_unit'+arm.removeprefix('graph')
            backend=engine(key,a.output/'graphs'/(arm+'.json'))
        else:
            if arm in {'e5','hybrid'}:
                for name,digest in protocol['e5_resources'].items():
                    if sha(RESOURCES/'e5'/name)!=digest:raise ValueError('E5 resource drift')
                os.environ['HF_HUB_CACHE']=read(RESOURCES/'e5/runtime-spec.json')['cache_folder']
                os.environ['HF_HUB_OFFLINE']='1';os.environ['TRANSFORMERS_OFFLINE']='1'
            backend=engine(arm,None)
    qs=read(a.output/'public-questions.json');random.Random(protocol['seed']).shuffle(qs)
    def worker(q):
        folder=a.output/'generation'/arm/q['id']; result_path=folder/'result.json'
        if result_path.exists():
            old=read(result_path)
            if old['protocol_sha256']!=sha(a.output/'protocol.json'):raise ValueError('Session protocol drift')
            return old['status']
        if (folder/'requests').exists():raise ValueError('Unresolved session preserved; automatic replay forbidden')
        client=DeploymentResponse(NeutralToolClient(routed_client('qwen3-8b',folder/'requests',workload='bulk',timeout=180)),
            'qwen3-8b',ANSWER_CHECKLIST)
        tools=KnowledgeToolSession(method,corpus,backend,KnowledgeBudget(**protocol['knowledge_budget']))
        started=time.monotonic()
        result=AutonomousKnowledgeAgent('qwen3-8b',tools,client,counter,ModelBudget(**protocol['model_budget'])).run(q['question'])
        result.update(id=q['id'],arm=arm,protocol_sha256=sha(a.output/'protocol.json'),seconds=time.monotonic()-started,
            delivered_lines=[dict(path=p,line=n) for p,n in sorted(tools.delivered_lines)])
        save(result_path,result)
        return result['status']
    counts=Counter();done=0
    with ThreadPoolExecutor(max_workers=protocol['workers_per_arm']) as pool:
        futures=[pool.submit(worker,q) for q in qs]
        for future in as_completed(futures):
            counts[future.result()]+=1;done+=1
            if done%10==0:print(arm,done,dict(counts),flush=True)
    save(a.output/'completion'/(arm+'.json'),dict(arm=arm,sessions=done,statuses=dict(counts),
        protocol_sha256=sha(a.output/'protocol.json'),results_sha256={q['id']:sha(a.output/'generation'/arm/q['id']/'result.json') for q in qs}))


def run(a):
    protocol=verify(a.output)
    def worker(arm):
        log=a.output/'logs'/(arm+'.log');log.parent.mkdir(exist_ok=True)
        if (a.output/'completion'/(arm+'.json')).exists():return arm,0
        with log.open('a',encoding='utf-8') as output:
            result=subprocess.run([sys.executable,'-X','utf8',str(Path(__file__).resolve()),'answer',
                '--output',str(a.output.resolve()),'--arm',arm],cwd=PROJECT,stdout=output,stderr=subprocess.STDOUT)
        print(arm,'exit',result.returncode,flush=True);return arm,result.returncode
    with ThreadPoolExecutor(max_workers=len(ARMS)) as pool: results=list(pool.map(worker,protocol['arms']))
    save(a.output/'generation-controller-completion.json',dict(arms=dict(results),
        complete=all(code==0 for _,code in results),protocol_sha256=sha(a.output/'protocol.json')))


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['prepare','answer','run'])
    p.add_argument('--output',type=Path,required=True);p.add_argument('--graph',type=Path);p.add_argument('--calibration',type=Path)
    p.add_argument('--arm',choices=ARMS);a=p.parse_args();globals()[a.command](a)


if __name__=='__main__':main()
