"""保持正式图与完整组行为，分离候选关系遍历和交付上下文。"""
import copy

from common import GRAPH, RESOURCES
from chapter2_knowledge_graph_v6 import BilingualScopeGraph, chinese_terms, alias_relevance
from chapter2_knowledge_graph_v4 import AdaptiveSourceGraph

class IndependentGraph(BilingualScopeGraph):
    def __init__(self, *args, relation_traversal=True, **kwargs):
        super().__init__(*args,**kwargs)
        self.relation_traversal=relation_traversal

    def initial_flat(self,query):
        # Skip v5's LITERAL_HEADING_REFERENCE lookup, which is itself an
        # edge traversal despite living inside the flat seed function.
        flat=AdaptiveSourceGraph._facet_flat(self,query)
        qt=chinese_terms(query)
        semantic={uid:alias_relevance(query,qt,aliases) for uid,aliases in self.source_aliases.items()}
        explicit_cases,_,_=self._scope(query)
        cases={}
        if self.semantic_policy=='case' and not explicit_cases:
            cases={c:alias_relevance(query,qt,a) for c,a in self.case_source_aliases.items()}
        for row in flat['items']:
            unit=self.graph['units'][self.nodes[row['node_id']]['unit_id']]
            own=semantic.get(unit['id'],0);scope=cases.get(unit.get('source_context',{}).get('case_directory'),0)
            row['score']+=8*own+8*scope
            row['reasons']['source_alias_bonus']=8*own
            row['reasons']['soft_case_source_alias_bonus']=8*scope
        flat['items'].sort(key=lambda r:(-r['score'],r['node_id']))
        flat['diagnostic']['seeds']=flat['items'][:self.options['seed_limit']]
        flat['diagnostic'].update(bilingual_policy=self.semantic_policy,
            semantic_case_scope='soft prior, no inferred alias can exclude a case',source_owned_alias_units=len(self.source_aliases))
        return flat

    def _facet_flat(self,query):
        if self.relation_traversal:return super()._facet_flat(query)
        old=self.options['with_paths']
        self.options['with_paths']=True
        try:return self.initial_flat(query)
        finally:self.options['with_paths']=old

    def rank(self,query):
        old=self.options['with_paths']
        if not self.relation_traversal:self.options['with_paths']=False
        try:
            result=super().rank(query)
            result['options']=dict(self.options)
            return result
        finally:
            self.options['with_paths']=old

def create_graph(relation_traversal=True, path=GRAPH, with_cross=True):
    return IndependentGraph(path,corpus=RESOURCES/'corpus',corpus_manifest=RESOURCES/'source-map.json',
        semantic_policy='unit',options=dict(with_cross=with_cross,with_conditions=False,with_paths=True),
        relation_traversal=relation_traversal)

def full_slots(engine, ranking):
    packet=engine.read_native(ranking)
    slots=[dict(path=r['path'],start=s['start'],end=s['end'],node_id=r['native_unit'],
                native_rank=r['native_rank'],delivery_role='anchor_and_context')
           for r in packet['items'] for s in r['ranges']][:10]
    return packet,slots

def anchor_slots(engine, ranking, full):
    """每个完整组槽位仅保留其命中节点锚点与该槽位范围的交集；不补候选。"""
    result=[]
    for slot in full:
        node=engine.nodes[slot['node_id']]
        for anchor in node['evidence']:
            a=max(slot['start'],anchor['start']);b=min(slot['end'],anchor['end'])
            if a<=b:
                result.append(dict(slot,start=a,end=b,delivery_role='literal_node_anchor'))
    return result
