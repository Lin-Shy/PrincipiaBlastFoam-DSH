"""Matched development QA: old/new graph, public inputs, recorded deployments."""
import argparse
from collections import Counter
from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path
import sys
from threading import RLock
import time

PROJECT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(PROJECT/'src'))
from chapter2_v2_retrieval_probe import read, save, sha
from chapter2_proxy_model_execution import run_per_model, MODELS

ANSWER_CHECKLIST='''作答检查（对所有检索方法相同）：先按用户问题中的每个问句和已给条件安排查询，搜索具体模型名、参数名及必要英文名称。首次命中不表示资料齐全；需要比较、默认值或适用条件时，补读相应说明与配置。最终回答按用户所问逐项说明，给出原文支持的定义、数值、判断及理由；区别默认与实例。不要添加无法核验的技术延伸或运行保证。最后检查是否遗漏问题中的子问。工具动作的action只能是tool，例如 {"action":"tool","name":"search","arguments":{"query":"具体标识与所需含义"}}；不要写action=search。最终动作严格使用final、answer、references三个字段。'''


def prepared_messages(messages,addendum):
    actual=deepcopy(messages)
    if addendum:
        actual[0]['content']+='\n'+addendum
    return actual


class DeploymentResponse:
    """Expose an explicit interface alias; preserve actual model in raw receipt."""
    def __init__(self,client,logical_model,addendum=''):
        self.client,self.logical_model=client,logical_model
        self.addendum=addendum

    def __call__(self,body,turn):
        actual={**body,'messages':prepared_messages(body['messages'],self.addendum)} if self.addendum else body
        record=self.client(actual,turn)
        if record['status']!='response':return record
        raw=record['raw_response']
        if raw.get('model')!=self.client.deployment.model:
            raise ValueError('Actual deployed model differs')
        return {**record,'response':{**raw,'model':self.logical_model},
            'response_interface_alias':dict(actual_model=raw['model'],logical_model=self.logical_model,
                policy='Explicit deployment alias only; original provider receipt unchanged.')}


def token_counter(raw,workload,addendum=''):
    def counter(messages):
        actual=prepared_messages(messages,addendum)
        if workload=='small':
            for message in reversed(actual):
                if message['role']=='user':
                    if not message['content'].rstrip().endswith('/no_think'):
                        message['content']+='\n/no_think'
                    break
        return raw(actual)
    return counter


def generate(args):
    from chapter2_qwen_routing import routed_client
    from chapter2_knowledge_input_guard import install
    guard=install(args.questions)
    from chapter2_autonomous_qa import load_tokenizer
    from principia_core.retrieval.knowledge_agent import AutonomousKnowledgeAgent,ModelBudget,SYSTEM
    from principia_core.retrieval.knowledge_qa import FrozenKnowledgeCorpus,KnowledgeToolSession,KnowledgeBudget
    from chapter2_knowledge_graph_retriever import KnowledgeGraphRetriever
    from chapter2_knowledge_graph_v2 import EvidenceGraphV2
    from chapter2_qa_backends import NativeBackend
    if args.output.exists():raise FileExistsError('New development run required; no request replay')
    resources=read(args.resources);questions=read(args.questions)
    if any(set(q)!={'id','question'} for q in questions):raise ValueError('Public questions only')
    corpus=FrozenKnowledgeCorpus(resources['corpus'],resources['corpus_manifest'])
    engines={}
    for method in args.methods:
        if method=='graph_v1':engines[method]=KnowledgeGraphRetriever(resources['graph_full'],resources['corpus'],corpus_manifest=resources['source_map'])
        elif method=='graph_v2':engines[method]=EvidenceGraphV2(args.graph_v2,resources['corpus'],corpus_manifest=resources['source_map'],evidence_policy=args.evidence_policy)
        elif method=='bm25':
            from chapter2_baseline_native import NoGraphBM25
            engines[method]=NoGraphBM25(resources['corpus'],resources['source_map'])
    counters,tokenizers={},{}
    for model in MODELS:
        raw,tokenizers[model]=load_tokenizer(Path(resources['tokenizer_'+model]),model)
        lock=RLock()
        def counter(messages,raw=raw,lock=lock):
            with lock:return raw(messages)
        counters[model]=token_counter(counter,args.workload,ANSWER_CHECKLIST if args.answer_checklist else '')
    model_budget=ModelBudget(output_tokens_per_request=args.output_tokens,
        final_output_reserve=args.output_tokens,output_tokens_total=max(16384,8*args.output_tokens))
    knowledge_budget=KnowledgeBudget()
    implementation=[Path(__file__),PROJECT/'experiments/retrieval_method/chapter2_proxy_model_execution.py',
        PROJECT/'experiments/retrieval_method/chapter2_knowledge_graph_v2.py',
        PROJECT/'experiments/retrieval_method/chapter2_knowledge_graph_retriever.py',
        PROJECT/'experiments/retrieval_method/chapter2_qa_backends.py',
        PROJECT/'experiments/retrieval_method/chapter2_qwen_local.py',
        PROJECT/'experiments/retrieval_method/chapter2_qwen_routing.py',
        PROJECT/'src/principia_core/retrieval/knowledge_agent.py',
        PROJECT/'src/principia_core/retrieval/knowledge_qa.py']
    if 'bm25' in args.methods:implementation.append(PROJECT/'experiments/retrieval_method/chapter2_baseline_native.py')
    protocol=dict(schema='matched_development_qa_v2',formal_result=False,workload=args.workload,
        workers_per_model=args.workers_per_model,models=list(MODELS),methods=args.methods,
        question_ids=[q['id'] for q in questions],questions_sha256=sha(args.questions),
        system_prompt=SYSTEM,model_budget=asdict(model_budget),knowledge_budget=asdict(knowledge_budget),
        tokenizer_bindings=tokenizers,input_guard=guard,evidence_policy=args.evidence_policy,
        graph_v1_sha256=sha(Path(resources['graph_full'])),graph_v2_sha256=sha(args.graph_v2),
        implementation_sha256={str(p.relative_to(PROJECT)):sha(p) for p in implementation},
        max_transport_attempts=1,content_retries=0,local_proxy_pooling=False)
    protocol['common_answer_checklist']=ANSWER_CHECKLIST if args.answer_checklist else ''
    protocol['matched_comparison_scope']='New development comparison only; shared prompt/output changes prevent treating historical sessions as matched controls.'
    save(args.output/'protocol.json',protocol)
    method_locks={m:RLock() for m in args.methods}
    jobs=[dict(model=m,method=method,question=q) for q in questions for method in args.methods for m in MODELS]
    statuses=Counter()
    def worker(item):
        model,method,q=item['model'],item['method'],item['question']
        folder=args.output/'sessions'/model/method/q['id']
        client=DeploymentResponse(routed_client(model,folder/'requests',workload=args.workload,timeout=args.timeout),model,
            ANSWER_CHECKLIST if args.answer_checklist else '')
        backend=NativeBackend(engines[method],graph=method!='bm25');backend.lock=method_locks[method]
        tools=KnowledgeToolSession('bm25' if method=='bm25' else 'graph',corpus,backend,knowledge_budget)
        started=time.monotonic()
        result=AutonomousKnowledgeAgent(model,tools,client,counters[model],model_budget).run(q['question'])
        result.update(question=q,development_method=method,formal_result=False,
            deployment_workload=args.workload,protocol_sha256=sha(args.output/'protocol.json'),
            native_ranking_events=backend.events,seconds=time.monotonic()-started)
        save(folder/'result.json',result)
        return result
    def observe(item,result):
        statuses[result['status']]+=1
        print(json.dumps(dict(completed=sum(statuses.values()),planned=len(jobs),model=item['model'],method=item['method'],id=item['question']['id'],status=result['status'])),flush=True)
        if result['status'] in {'transport_error','http_rejected','model_mismatch','model_identity_mismatch'}:
            raise RuntimeError('Deployment circuit: no new admissions, drain all started work, no retries')
    try:
        run_per_model(jobs,worker,observe,model_of=lambda r:r['model'],workers_per_model=args.workers_per_model)
    except Exception:
        save(args.output/'stopped.json',dict(planned=len(jobs),completed=sum(statuses.values()),statuses=dict(statuses),requests_reissued=False))
        raise
    save(args.output/'completion.json',dict(planned=len(jobs),completed=sum(statuses.values()),statuses=dict(statuses),complete=True))


def score(args):
    from chapter2_qwen_routing import routed_client
    from chapter2_autonomous_qa import load_tokenizer
    from chapter2_score_knowledge_formal import score_answer
    from chapter2_answer_scoring import scoring_payload
    from chapter2_knowledge_evaluation import delivered_lines
    from principia_core.retrieval.knowledge_qa import FrozenKnowledgeCorpus
    protocol=read(args.input/'protocol.json');completion=read(args.input/'completion.json')
    if not completion['complete']:raise ValueError('Generation must be complete')
    if args.output.exists():raise FileExistsError('New independent scoring run required')
    annotations={r['id']:r for r in read(args.dataset/'scoring/annotations.json')}
    evidence=read(args.dataset/'scoring/evidence.json');split=read(args.dataset/'split.json')
    if not set(protocol['question_ids'])<=set(split['ids']['dev']):raise ValueError('Development answers only')
    if args.workload!=protocol['workload']:raise ValueError('Do not silently mix generation and judge deployments')
    resources=read(args.resources);corpus=FrozenKnowledgeCorpus(resources['corpus'],resources['corpus_manifest'])
    public_questions={q['id']:q['question'] for q in read(args.dataset/'model/questions.json')}
    reuse_root=getattr(args,'reuse_scores',None)
    if reuse_root is not None:
        if args.workload!='bulk':raise ValueError('Exact request reuse is registered only for the same proxy deployment')
        old=read(reuse_root/'protocol.json');closed=read(reuse_root/'completion.json')
        if not closed['complete'] or old['workload']!='bulk' or old['generation_protocol_sha256']!=sha(args.input/'protocol.json'):
            raise ValueError('Old scores must bind the complete identical generation')
    raw,tokenizer=load_tokenizer(Path(resources['tokenizer_qwen3-14b']),'qwen3-14b')
    lock=RLock()
    def count(messages):
        with lock:return raw(messages)
    counter=token_counter(count,args.workload)
    jobs=[dict(model=m,method=method,id=qid) for m in protocol['models'] for method in protocol['methods'] for qid in protocol['question_ids']]
    from chapter2_partial_answer_scoring import COVERAGE_PROMPT,SOURCE_PROMPT
    save(args.output/'protocol.json',dict(schema='development_v7_original_rubric_scoring_v2',formal_result=False,
        generation_protocol_sha256=sha(args.input/'protocol.json'),workload=args.workload,
        judge_model='qwen3-14b',workers_per_model=args.workers_per_model,
        rubric_version='source_free_v7',coverage_prompt=COVERAGE_PROMPT,source_prompt=SOURCE_PROMPT,
        scorer_sha256=sha(PROJECT/'experiments/retrieval_method/chapter2_score_knowledge_formal.py'),
        annotations_sha256=sha(args.dataset/'scoring/annotations.json'),evidence_sha256=sha(args.dataset/'scoring/evidence.json'),
        tokenizer=tokenizer,independent_human_truth=False,
        scoring_driver_sha256=sha(Path(__file__)),
        exact_request_reuse_protocol_sha256=sha(reuse_root/'protocol.json') if reuse_root else None,
        reused_verdict_policy='Identical full request and same deployment only. Changed hypotheses get new calls; old failures are never replayed.'))
    statuses=Counter()
    def worker(item):
        model,method,qid=item['model'],item['method'],item['id']
        path=args.input/'sessions'/model/method/qid/'result.json';result=read(path)
        if result['question']!={'id':qid,'question':public_questions[qid]}:
            raise ValueError('Changed questions require new generated answers, not retrospective rescoring')
        payload=scoring_payload(result['question']['question'],annotations[qid],evidence,corpus,result['answer'],delivered_lines(result)) if result['status']=='answered' else None
        folder=args.output/'sessions'/model/method/qid
        base=routed_client('qwen3-14b',folder/'requests',workload=args.workload,timeout=args.timeout)
        reuse=None
        if reuse_root:
            from chapter2_exact_judge_reuse import ExactJudgeReuse
            source=reuse_root/'sessions'/model/method/qid
            oldscore=read(source/'score.json')
            if oldscore['result_sha256']!=sha(path):raise ValueError('Reuse source binds another answer')
            reuse=ExactJudgeReuse(base,source/'requests',folder/'reuse-references');base=reuse
        client=DeploymentResponse(base,'qwen3-14b')
        value=score_answer(result,payload,client,counter)
        value.update(result_sha256=sha(path),generation_status=result['status'],model=model,method=method,id=qid,
            group=annotations[qid]['split_group'],formal_result=False)
        if reuse:
            value['exact_request_reuse']=dict(reused=reuse.reused,fresh=reuse.fresh,
                new_transport_failed=reuse.new_transport_failed)
        save(folder/'score.json',value)
        return value
    def observe(item,value):
        statuses[value['status']]+=1
        print(json.dumps(dict(scored=sum(statuses.values()),planned=len(jobs),status=value['status'])),flush=True)
        if (value.get('generation_status')=='answered' and value.get('reason') in {'transport_error','http_rejected'}
            and (not reuse_root or value.get('exact_request_reuse',{}).get('new_transport_failed'))):
            raise RuntimeError('Judge deployment circuit; drain without retry')
    try:
        run_per_model(jobs,worker,observe,model_of=lambda r:'qwen3-14b',workers_per_model=args.workers_per_model)
    except Exception:
        save(args.output/'stopped.json',dict(planned=len(jobs),completed=sum(statuses.values()),statuses=dict(statuses)))
        raise
    save(args.output/'completion.json',dict(planned=len(jobs),completed=sum(statuses.values()),statuses=dict(statuses),complete=True))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    sub=parser.add_subparsers(dest='command',required=True)
    for command in ('generate','score'):
        p=sub.add_parser(command)
        for name in ('resources','output'):p.add_argument('--'+name,type=Path,required=True)
        p.add_argument('--workload',choices=['bulk','small'],required=True)
        p.add_argument('--workers-per-model',type=int)
        p.add_argument('--timeout',type=int,default=180)
        if command=='generate':
            p.add_argument('--questions',type=Path,required=True)
            p.add_argument('--graph-v2',type=Path,required=True)
            p.add_argument('--methods',nargs='+',choices=['bm25','graph_v1','graph_v2'],default=['bm25','graph_v1','graph_v2'])
            p.add_argument('--evidence-policy',choices=['compact','whole'],default='compact')
            p.add_argument('--answer-checklist',action='store_true')
            p.add_argument('--output-tokens',type=int,choices=[2048,4096],default=2048)
        else:
            p.add_argument('--input',type=Path,required=True)
            p.add_argument('--dataset',type=Path,required=True)
            p.add_argument('--reuse-scores',type=Path)
    args=parser.parse_args()
    args.workers_per_model=args.workers_per_model or (16 if args.workload=='bulk' else 1)
    if not 1<=args.workers_per_model<=16 or (args.workload=='small' and args.workers_per_model!=1):
        raise ValueError('Bulk up to sixteen per model; local diagnosis one per model')
    (generate if args.command=='generate' else score)(args)


if __name__=='__main__':main()
