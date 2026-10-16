"""Gold-isolated graph-development candidates with the same source budgets."""
import argparse
from pathlib import Path
import time
import json
from chapter2_v2_retrieval_probe import read,save,sha,evaluate,PROJECT


def retrieve(a):
    from chapter2_knowledge_input_guard import install
    guard=install(a.questions)
    from chapter2_knowledge_graph_v3 import SourceContextGraph
    from chapter2_qa_backends import NativeBackend
    from principia_core.retrieval.knowledge_qa import FrozenKnowledgeCorpus,KnowledgeToolSession,KnowledgeBudget
    if a.output.exists():raise FileExistsError('New immutable development run required')
    resources=read(a.resources);questions=read(a.questions)
    if any(set(q)!={'id','question'} for q in questions):raise ValueError('Only public natural questions')
    corpus=FrozenKnowledgeCorpus(resources['corpus'],resources['corpus_manifest'])
    methods={'source_context':dict(), 'context_only':dict(identity_ranking=False),
        'identity_only':dict(context_characters=0),'adjacent_context':dict(parent_retrieval=False)}
    bindings={str(p):sha(p) for p in [a.questions,a.resources,a.graph,Path(__file__),
        PROJECT/'experiments/retrieval_method/chapter2_knowledge_graph_v3.py',
        PROJECT/'experiments/retrieval_method/chapter2_knowledge_graph_v2.py',
        PROJECT/'experiments/retrieval_method/chapter2_knowledge_graph_retriever.py']}
    save(a.output/'protocol.json',dict(schema='public_query_source_parent_graph_probe_v1',formal_result=False,
        input_sha256=bindings,questions=len(questions),methods=a.methods,input_guard=guard,
        context_characters=a.context_characters,budgets=[6000,12000,24000],model_calls=0,
        query_policy='identical unmodified public natural question',
        limitations=['Exploratory development; source-owned parent expansion is not a semantic entailment claim.']))
    for method in a.methods:
        options=dict(context_characters=a.context_characters,**methods[method]) if method!='identity_only' else methods[method]
        engine=SourceContextGraph(a.graph,resources['corpus'],corpus_manifest=resources['source_map'],**options)
        backend=NativeBackend(engine,graph=True)
        for q in questions:
            start=time.monotonic();packet,stats=backend.ranked(q['question'],64)
            candidates=[dict(path=r['path'],start=s['start'],end=s['end']) for r in packet['items'] for s in r['ranges']]
            deliveries={}
            for cap in [6000,12000,24000]:
                tools=KnowledgeToolSession('graph',corpus,backend,KnowledgeBudget(tool_calls=1,tool_characters=cap,total_characters=cap))
                encoded,lines=tools._deliver(candidates[:10],cap)
                deliveries[str(cap)]=dict(characters=len(encoded),original_lines=[dict(path=p,line=n) for p,n in lines],response=json.loads(encoded) if encoded else None)
            save(a.output/'rankings'/method/(q['id']+'.json'),dict(id=q['id'],query=q['question'],method=method,
                candidates=candidates,deliveries=deliveries,native_packet=packet,stats=stats,seconds=time.monotonic()-start))
        print(json.dumps(dict(method=method,questions=len(questions),status='complete')),flush=True)
    save(a.output/'completion.json',dict(complete=True,questions=len(questions),methods=a.methods,model_calls=0))


def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='command',required=True)
    r=sub.add_parser('retrieve')
    for n in ('resources','questions','graph','output'):r.add_argument('--'+n,type=Path,required=True)
    r.add_argument('--methods',nargs='+',choices=['source_context','context_only','identity_only','adjacent_context'],default=['source_context','context_only'])
    r.add_argument('--context-characters',type=int,default=2400)
    e=sub.add_parser('evaluate')
    for n in ('input','dataset','output'):e.add_argument('--'+n,type=Path,required=True)
    a=p.parse_args();retrieve(a) if a.command=='retrieve' else evaluate(a)


if __name__=='__main__':main()
