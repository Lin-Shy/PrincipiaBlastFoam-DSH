"""Graph-only relevance, facet diversity and degree-normalized propagation."""
from collections import defaultdict
import re
import time

from chapter2_knowledge_graph_v4 import AdaptiveSourceGraph, query_identifiers
from chapter2_knowledge_graph_v2 import RELATION_DECAY
from chapter2_knowledge_graph_retriever import present
from chapter2_knowledge_graph_v3 import identity_fold


class FocusedEvidenceGraph(AdaptiveSourceGraph):
    POLICIES = {'balanced', 'focused', 'ppr', 'ppr_focused', 'gated', 'compact', 'expanded', 'neutral', 'adaptive'}
    def __init__(self,*args,policy='balanced',**kwargs):
        if policy not in self.POLICIES:raise ValueError('Unknown focused graph policy')
        super().__init__(*args,**kwargs)
        self.policy=policy
        if policy in {'compact','adaptive'}:self.context_characters=1200
        if policy=='expanded':self.context_characters=4800
        self.unit_identity={uid:identity_fold(u['text']) for uid,u in self.graph['units'].items()}

    def _facet_flat(self,query):
        flat=super()._facet_flat(query)
        best={}
        for row in flat['items']:
            uid=self.nodes[row['node_id']]['unit_id']
            if uid not in best or row['score']>best[uid]['score']:best[uid]=row
        leaders=sorted(best.values(),key=lambda r:-r['score'])[:8]
        allowed_units={self.nodes[r['node_id']]['unit_id']:r for r in leaders}
        by_node={r['node_id']:r for r in flat['items']}
        ids=query_identifiers(query)
        cases,manual_only,tutorial_only=self._scope(query)
        for source,neighbors in self.adjacency.items():
            uid=self.nodes[source]['unit_id']
            if uid not in allowed_units:continue
            for target,edge,direction in neighbors:
                if edge['relation']!='LITERAL_HEADING_REFERENCE' or direction!='forward':continue
                if not self._allowed(self.nodes[target],cases,manual_only,tutorial_only):continue
                source_row=allowed_units[uid]
                # An explicit selector key gates the documentation lookup.
                # Otherwise retain a bounded low-priority reference candidate.
                key=str(edge.get('support',{}).get('selector_key','')).casefold()
                value=source_row['score']*(.88 if key in ids else .65)
                if target not in by_node or value>by_node[target]['score']:
                    by_node[target]=dict(node_id=target,score=value,origin=source_row['origin'],visited=[source,target],
                        route=[dict(edge_id=edge['id'],relation=edge['relation'],direction=direction,
                            cross_owner=edge['cross_owner'],condition_evaluated=False)],
                        reasons=dict(literal_documentation_lookup=True,selector_key=key))
        flat['items']=sorted(by_node.values(),key=lambda r:(-r['score'],r['node_id']))
        flat['diagnostic']['seeds']=flat['items'][:self.options['seed_limit']]
        return flat

    def _propagate(self, flat, query):
        """Normalized walk on allowed typed graph edges; source anchors retained."""
        seeds=flat['diagnostic']['seeds'];total=sum(max(0,r['score']) for r in seeds)
        if total<=0:return {},0
        restart={r['node_id']:max(0,r['score'])/total for r in seeds}
        mass=restart.copy();visits=defaultdict(float);expanded=0
        cases,manual_only,tutorial_only=self._scope(query)
        for _ in range(3):
            nxt=defaultdict(float)
            for node,value in mass.items():
                neighbors=[]
                for target,edge,direction in self.adjacency[node]:
                    weight=RELATION_DECAY.get(edge['relation'])
                    if weight is None:continue
                    if edge['relation']=='FILE_SELECTOR_CONTEXT' and direction!='forward':continue
                    if not self._allowed(self.nodes[target],cases,manual_only,tutorial_only):continue
                    neighbors.append((target,weight))
                denom=sum(w for _,w in neighbors)
                if denom:
                    for target,weight in neighbors:
                        nxt[target]+=.65*value*weight/denom;expanded+=1
            for node,value in restart.items():nxt[node]+=.35*value
            mass=dict(nxt)
            for node,value in mass.items():visits[node]+=value/3
        unit_mass=defaultdict(float)
        for nid,value in visits.items():unit_mass[self.nodes[nid]['unit_id']]+=value
        return unit_mass,expanded

    def rank(self,query):
        started=time.monotonic()
        previous=super().rank(query)
        ids=query_identifiers(query)
        pool=[]
        for row in previous['items']:
            uid=self.nodes[row['node_id']]['unit_id'];u=self.graph['units'][uid]
            hits={word for word in ids if present(self.unit_identity[uid],word)}
            headings=u.get('context',[])
            scope=(u['path'],headings[-1]['line'] if headings else u['owner'])
            pool.append({**row,'facet_hits':hits,'scope_key':scope})
        propagation={};edges=0
        if self.policy.startswith('ppr'):
            propagation,edges=self._propagate(self._facet_flat(query),query)
        max_mass=max(propagation.values(),default=1)
        selected=[];seen_facets=set();path_counts=defaultdict(int);scope_counts=defaultdict(int)
        while pool and len(selected)<self.options['native_limit']:
            def priority(row):
                uid=self.nodes[row['node_id']]['unit_id']
                if self.policy=='neutral':return row['score']
                novel=len(row['facet_hits']-seen_facets)/max(1,len(ids))
                value=row['score']*(1+.35*novel)
                if propagation:value+=8*propagation.get(uid,0)/max_mass
                # Diversity within one logical section matters more than
                # spreading unrelated hits over many physical files.
                return value/(1+.03*path_counts[row['path']]+.12*scope_counts[row['scope_key']])
            row=min(pool,key=lambda r:(-priority(r),r['path'],self.graph['units'][self.nodes[r['node_id']]['unit_id']]['start']))
            pool.remove(row);row['selection_score']=priority(row)
            path_counts[row['path']]+=1;scope_counts[row['scope_key']]+=1;seen_facets|=row['facet_hits']
            row['facet_hits']=sorted(row['facet_hits']);row['scope_key']=list(row['scope_key'])
            selected.append({**row,'native_rank':len(selected)+1})
        result={**previous,'schema':'focused_evidence_graph_v5','items':selected}
        result['diagnostic']={**previous['diagnostic'],'v5_policy':self.policy,'degree_normalized_walk_edges':edges,
            'graph_scan_seconds_and_ranking':time.monotonic()-started,'external_index_loaded':False,
            'query_or_gold_specific_weights':False,'question_or_result_cache':False,
            'public_query_identifiers':sorted(ids)}
        return result

    def read_for_budget(self,ranking,characters):
        if type(characters) is not int or characters<1:raise ValueError('Positive source delivery budget required')
        old=self.context_characters
        self.context_characters=min(2400,max(1200,characters//5))
        try:return self.read_native(ranking)
        finally:self.context_characters=old

    def read_native(self,ranking):
        if self.policy=='gated':
            ids=set(ranking['diagnostic']['public_query_identifiers'])
            hits={self.nodes[r['node_id']]['unit_id'] for r in ranking['items'][:self.context_seed_limit]}
            seen=set();items=[]
            for row in ranking['items']:
                uid=self.nodes[row['node_id']]['unit_id'];unit=self.graph['units'][uid]
                selected,routes,decisions=self._select_context(row,hits)
                heading=unit.get('context',[])
                ancestors={v['line'] for v in heading}
                fresh=[]
                for k,v in selected.items():
                    same_heading=v.get('context',[])==heading
                    explicit=any(present(self.unit_identity[k],word) for word in ids)
                    introduction=v['start'] in ancestors
                    if k not in seen and (k==uid or same_heading or explicit or introduction):fresh.append(v)
                if not fresh:continue
                fresh.sort(key=lambda v:(v['id']!=uid,v['start']))
                ranges=[]
                for v in fresh:
                    if ranges and ranges[-1]['end']+1==v['start']:ranges[-1]['end']=v['end']
                    else:ranges.append(dict(start=v['start'],end=v['end']))
                    seen.add(v['id'])
                items.append(dict(path=row['path'],ranges=ranges,native_unit=row['node_id'],native_rank=row['native_rank'],
                    owner=row['owner'],original_sha256=self.hashes[row['path']],read_policy='query_gated_original_context',
                    context_fragments=[dict(unit_id=v['id'],start=v['start'],end=v['end'],route=routes[v['id']]) for v in fresh]))
            return dict(items=items,ranking_diagnostic=ranking['diagnostic'],native_ranking=ranking)
        if not self.policy.endswith('focused'):return super().read_native(ranking)
        # Gated physical context: retain a located fragment's immediate
        # continuation, then allocate further context to other ranked anchors.
        old=self.context_seed_limit
        self.context_seed_limit=5
        try:return super().read_native(ranking)
        finally:self.context_seed_limit=old
