"""固定问题检索进程：仅id/question，禁止评分和网络访问。"""
import argparse
import os
import sys
import time

from common import *

METHODS=['graph','bm25','bge_m3','bm25_bge_m3','bm25_parent','no_traversal','anchor_only',
         'e5','bm25_e5','no_cross','no_aliases']
BUDGETS=[2000,4000,6000]

def install_guard():
    from chapter2_knowledge_input_guard import install
    install(QUESTIONS)
    opened=set()
    def hook(event,args):
        if event=='open' and args and isinstance(args[0],(str,bytes,os.PathLike)):
            opened.add(Path(os.fsdecode(args[0])).resolve().as_posix())
        if event in {'socket.connect','socket.connect_ex','socket.getaddrinfo'}:
            raise PermissionError('offline retrieval cannot access network')
    sys.addaudithook(hook)
    return opened

def canonical_ranges(slots):
    """前10槽位先固定；消除所有重复行，不因去重回填新候选。"""
    seen=set();result=[]
    for row in slots:
        fresh=[n for n in range(row['start'],row['end']+1) if (row['path'],n) not in seen]
        for n in fresh:
            if result and result[-1]['path']==row['path'] and result[-1]['end']+1==n and result[-1].get('slot')==row.get('slot'):
                result[-1]['end']=n
            else:
                result.append(dict(row,start=n,end=n))
            seen.add((row['path'],n))
    return result

class SlotsBackend:
    def __init__(self,slots):self.slots=canonical_ranges([dict(s,slot=i) for i,s in enumerate(slots)])
    def search(self,query,limit):
        return [dict(path=s['path'],start=s['start'],end=s['end']) for s in self.slots]

class TextEngine:
    def __init__(self,method):
        from text_baselines import BM25,ParentBM25,RRF
        self.method=method;start=time.monotonic()
        if method in ['bm25','bm25_parent','bm25_bge_m3','bm25_e5']:
            self.bm25=BM25()
        if method in ['bge_m3','bm25_bge_m3']:
            from bge_m3_dense import BGEDense
            self.dense=BGEDense()
        if method in ['e5','bm25_e5']:
            from chapter2_qa_backends import create_backend
            os.environ['HF_HUB_CACHE']=str(PROJECT/'.local/knowledge-qa-hf')
            os.environ['HF_HUB_OFFLINE']='1';os.environ['TRANSFORMERS_OFFLINE']='1'
            self.e5=create_backend('e5',RESOURCES/'corpus',RESOURCES/'source-map.json',e5_index=RESOURCES/'e5')
        if method=='bm25_parent':self.parent=ParentBM25(self.bm25)
        if method=='bm25_bge_m3':self.rrf=RRF(self.bm25,self.dense)
        if method=='bm25_e5':self.rrf=RRF(self.bm25,E5Rank(self.e5))
        self.load_seconds=time.monotonic()-start

    def query(self,query):
        if self.method=='bm25':rows=self.bm25.rank(query)
        elif self.method=='bm25_parent':rows=self.parent.rank(query)
        elif self.method=='bge_m3':rows=self.dense.rank(query)
        elif self.method=='e5':rows=E5Rank(self.e5).rank(query)
        else:rows=self.rrf.rank(query)
        trace=dict(ranking=rows,graph_loaded=False)
        if hasattr(self,'rrf'):trace['fusion']=self.rrf.last_trace
        return rows[:10],trace

class E5Rank:
    def __init__(self,backend):self.backend=backend
    def rank(self,query,limit=64):
        packet,stats=self.backend.ranked(query,limit)
        return [dict(path=r['path'],start=s['start'],end=s['end'],score=r['score'],native_rank=r['native_rank'])
                for r in packet['items'] for s in r['ranges']]

class GraphEngine:
    def __init__(self,method):
        from graph_ablations import create_graph
        self.method=method
        path=GRAPH if method not in ['no_cross','no_aliases'] else GRAPH.with_name(method+'.json')
        self.engine=create_graph(method!='no_traversal',path=path,with_cross=method!='no_cross')
        self.load_seconds=self.engine.load_seconds

    def query(self,query):
        from graph_ablations import full_slots,anchor_slots
        ranking=self.engine.rank(query)
        packet,slots=full_slots(self.engine,ranking)
        result=anchor_slots(self.engine,ranking,slots) if self.method=='anchor_only' else slots
        old=self.engine.options['with_paths']
        # Preserve the independent initial scan definition for every graph arm.
        self.engine.options['with_paths']=True
        initial=self.engine.initial_flat(query)['diagnostic']['seeds']
        self.engine.options['with_paths']=old
        return result,dict(ranking=ranking,packet=packet,full_slots=slots,selected_slots=result,
                           initial_seeds_before_relation_lookup=initial,graph_loaded=True)

def freeze():
    audit=read(ARCHIVE/'audit/checks.json')
    if not all(audit['checks'].values()):raise ValueError('audit required')
    sources={p.name:sha(p) for p in HERE.glob('*.py')}
    save(ARCHIVE/'configs/retrieval_v1.json',dict(schema='round2_fixed_query_v1',status='frozen_before_retrieval',
         methods=METHODS,budgets=BUDGETS,question_count=200,questions_sha256=sha(QUESTIONS),
         graph_sha256=sha(GRAPH),source_map_sha256=sha(RESOURCES/'source-map.json'),
         code=sources,legacy_code=audit['implementation_bindings'],seed=20261020,
         query='unaltered natural-language question; no planner, no translation, no scoring inputs',
         slots=10,dedup='unique original source lines after fixed candidate slots; no candidate backfill',
         delivery='historical KnowledgeToolSession._deliver; complete source lines; all compact JSON envelope characters counted',
         b3='first10 anchors; independent nearest containing Markdown/brace parent <=1200 total text else adjacent full lines <=1200 extra; anchor first',
         a1='disable v5 literal reference lookup and v4 traversal, preserve v4 initial scan/static bonuses and context',
         a2='full graph first10 slots fixed; intersect node evidence anchors with same slots; no refill',
         cache='BM25 frozen-corpus statistics cached; graph frozen forward fields; no query result cache; rank once, deliver at three budgets',
         design_sha256=sha(WORKSPACE/'graduation-thesis-materials/graduation-research/chapters/chapter02.md'),
         task_sha256=sha(WORKSPACE/'Codex_Chapter2_RAG_Round2_Experiment_Plan.md'),
         e2e_status='not approved, not started',holdout_status='not approved, no new holdout evaluation'))
    runtime=ARCHIVE/'runtime_v1'
    runtime.mkdir(exist_ok=False)
    for p in HERE.glob('*.py'):(runtime/p.name).write_bytes(p.read_bytes())
    print('frozen',sha(ARCHIVE/'configs/retrieval_v1.json'))

def run(method,run_id,smoke=False):
    protocol=ARCHIVE/'configs/retrieval_v1.json';p=read(protocol)
    if any(sha(HERE/n)!=h for n,h in p['code'].items()):raise ValueError('round2 implementation drift')
    if any(sha(PROJECT/n)!=v['expected'] for n,v in p['legacy_code'].items()):raise ValueError('legacy implementation drift')
    if sha(QUESTIONS)!=p['questions_sha256'] or sha(RESOURCES/'source-map.json')!=p['source_map_sha256']:
        raise ValueError('input drift')
    if method in ['graph','no_traversal','anchor_only'] and sha(GRAPH)!=p['graph_sha256']:
        raise ValueError('graph drift')
    out=ARCHIVE/'runs'/run_id/method
    out.mkdir(parents=True,exist_ok=False)
    save(out/'started.json',dict(method=method,protocol_sha256=sha(protocol),smoke=smoke,paid_calls=0))
    opened=install_guard()
    from principia_core.retrieval.knowledge_qa import FrozenKnowledgeCorpus,KnowledgeToolSession,KnowledgeBudget
    corpus=FrozenKnowledgeCorpus(RESOURCES/'corpus',RESOURCES/'corpus-manifest.json')
    start=time.monotonic()
    engine=GraphEngine(method) if method in ['graph','no_traversal','anchor_only','no_cross','no_aliases'] else TextEngine(method)
    loaded=time.monotonic()-start
    questions=public_questions() if not smoke else [dict(id='smoke-public',question='What does fieldValue mean in adaptive mesh refinement?')]
    with (out/'deliveries.jsonl').open('x',encoding='utf-8') as stream:
        for i,q in enumerate(questions,1):
            begin=time.monotonic();slots,trace=engine.query(q['question']);rank_seconds=time.monotonic()-begin
            save(out/'traces'/(q['id']+'.json'),trace)
            for cap in BUDGETS:
                tools=KnowledgeToolSession('bm25',corpus,SlotsBackend(slots),KnowledgeBudget(1,cap,cap))
                encoded=tools.execute('search',{'query':q['question']})
                event=tools.events[0]
                payload=read_wire(encoded)
                assert len(encoded)<=cap
                if event['status']!='returned' or 'evidence' not in payload:
                    raise ValueError('retrieval delivery error; retain failed run')
                ledger=event['delivered_original_lines']
                assert len(ledger)==len({(r['path'],r['line']) for r in ledger})
                stream.write(wire(dict(id=q['id'],question=q['question'],method=method,budget=cap,
                    response=encoded,response_sha256=__import__('hashlib').sha256(encoded.encode()).hexdigest(),
                    response_characters=len(encoded),delivered_lines=ledger,ranking_seconds=rank_seconds,
                    delivery_seconds=event['seconds'],truncated=payload['truncated']))+'\n')
            stream.flush()
            if i%20==0:print(method,i,'/',len(questions),flush=True)
    forbidden=[s for s in opened if '/scoring/' in s.casefold()]
    graph_reads=[s for s in opened if s.endswith('/selected.json') or s.endswith('/no_cross.json') or s.endswith('/no_aliases.json')]
    if forbidden or (method in ['bm25','bm25_parent','bge_m3','bm25_bge_m3','e5','bm25_e5'] and graph_reads):
        raise ValueError('production input isolation violation')
    save(out/'completed.json',dict(method=method,questions=len(questions),deliveries=len(questions)*3,
         load_seconds=loaded,wall_seconds=time.monotonic()-start,protocol_sha256=sha(protocol),
         deliveries_sha256=sha(out/'deliveries.jsonl'),trace_hashes={q['id']:sha(out/'traces'/(q['id']+'.json')) for q in questions},
         opened_files=sorted(opened),graph_reads=graph_reads,scoring_reads=forbidden,
         packages={n:__import__('importlib.metadata',fromlist=['version']).version(n) for n in ['numpy','transformers']},
         paid_calls=0,smoke=smoke))
    print(method,'complete',round(time.monotonic()-start,2),flush=True)

def read_wire(value):
    import json
    return json.loads(value)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['freeze','run'])
    p.add_argument('--method',choices=METHODS);p.add_argument('--run-id');p.add_argument('--smoke',action='store_true')
    args=p.parse_args()
    if args.action=='freeze':freeze()
    else:
        if not args.method or not args.run_id:p.error('method and unique run-id required')
        run(args.method,args.run_id,args.smoke)
