"""Current source-only graph and text ranking backends."""
import os,time
from common import *

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
