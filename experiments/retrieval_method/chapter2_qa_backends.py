"""Isolated ranking adapters: model-facing text always comes from raw sources."""
from threading import RLock

class NativeBackend:
    def __init__(self,engine,graph=False):self.engine=engine;self.graph=graph;self.events=[];self.lock=RLock()
    def ranked(self,query,limit):
        if self.graph:
            ranking=self.engine.rank(query)
            packet=self.engine.read_native(ranking)
            stats=packet['ranking_diagnostic']
        else:packet,stats=self.engine.query(query,{},limit)
        return packet,stats
    def search(self,query,limit):
        with self.lock:
            packet,stats=self.ranked(query,limit)
            self.events.append({'query':query,'native_packet':packet,'stats':stats})
        return [{'path':r['path'],'start':span['start'],'end':span['end']}
            for r in packet['items'] for span in r['ranges']][:limit]

class HybridBackend:
    def __init__(self,bm25,e5):self.bm25=bm25;self.e5=e5;self.events=[];self.lock=RLock()
    def ranked(self,query,limit):
        left,ls=self.bm25.ranked(query,64);right,rs=self.e5.ranked(query,64)
        scores={}
        for packet in (left,right):
            seen=set()
            for rank,row in enumerate(packet['items'],1):
                for span in row['ranges']:
                    key=(row['path'],span['start'],span['end'])
                    if key not in seen:scores[key]=scores.get(key,0)+1/(60+rank);seen.add(key)
        order=sorted(scores,key=lambda k:(-scores[k],k))[:limit]
        rows=[dict(path=p,start=a,end=b,score=scores[(p,a,b)],native_rank=i,
            native_unit=f'{p}:{a}:{b}') for i,(p,a,b) in enumerate(order,1)]
        packet=self.bm25.engine.sources.map(rows)
        return packet,{'bm25':ls,'e5':rs,'fusion':'RRF_k60_pool64','graph_loaded':False,
            'rank_is_before_character_budget':True}
    def search(self,query,limit):
        with self.lock:
            left,ls=self.bm25.ranked(query,64);right,rs=self.e5.ranked(query,64)
            scores={}
            for packet in (left,right):
                seen=set()
                for rank,row in enumerate(packet['items'],1):
                    for span in row['ranges']:
                        key=(row['path'],span['start'],span['end'])
                        if key not in seen:scores[key]=scores.get(key,0)+1/(60+rank);seen.add(key)
            order=sorted(scores,key=lambda k:(-scores[k],k))[:limit]
            self.events.append({'query':query,'bm25_native':left,'e5_native':right,'stats':{'bm25':ls,'e5':rs},
              'fusion':'RRF_k60_pool64','ranking':[{'path':p,'start':a,'end':b,'score':scores[(p,a,b)]} for p,a,b in order]})
        return [{'path':p,'start':a,'end':b} for p,a,b in order]

def create_backend(method,corpus,source_map,*,e5_index=None,graph=None,graph_options=None):
    if method=='bm25':
        from chapter2_baseline_native import NoGraphBM25
        return NativeBackend(NoGraphBM25(corpus,source_map))
    if method=='e5':
        if e5_index is None:raise ValueError('frozen E5 index required')
        import hashlib,json
        from pathlib import Path
        from candidate_hybrid import local_snapshot
        manifest=json.loads((Path(e5_index)/'manifest.json').read_text(encoding='utf-8'))
        folder=local_snapshot(manifest['model'])
        if not all(hashlib.sha256((folder/name).read_bytes()).hexdigest()==value for name,value in manifest['model_files'].items()):
            raise ValueError('frozen embedding weights changed')
        from chapter2_baseline_native import DenseE5
        return NativeBackend(DenseE5(corpus,source_map,e5_index))
    if method=='hybrid':
        return HybridBackend(create_backend('bm25',corpus,source_map),create_backend('e5',corpus,source_map,e5_index=e5_index))
    if method=='graph':
        if graph is None:raise ValueError('frozen independent-corpus graph required')
        from chapter2_knowledge_graph_retriever import KnowledgeGraphRetriever
        return NativeBackend(KnowledgeGraphRetriever(graph,corpus,options=graph_options,corpus_manifest=source_map),graph=True)
    raise ValueError('no ranking adapter for method')
