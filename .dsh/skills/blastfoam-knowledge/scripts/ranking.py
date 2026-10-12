"""Bounded, query-aware evidence paths. No corpus-specific rules or learned weights."""
from collections import defaultdict
import math
import re


def select_evidence(query, graph, documents, scores, initial, limit, make_result, canonical_case=None):
    nodes={n['id']:n for n in graph['nodes']}
    byid={d['id']:d for d in documents}
    byfile=defaultdict(list)
    outgoing=defaultdict(list); incoming=defaultdict(list)
    for d in documents:
        byfile[d['evidence']['path']].append(d)
    for e in graph['edges']:
        outgoing[e['source']].append(e); incoming[e['target']].append(e)
    # Stable iteration and max support make results independent of edge order/duplicates.
    for adjacency in (outgoing,incoming):
        for es in adjacency.values():
            es.sort(key=lambda e:(e['relation'],e['source'],e['target']))
    lexical={d['id']:(s,m) for s,d,m in scores}
    maximum=max((s for s,_,_ in scores),default=1.) or 1.
    wants_examples=bool(canonical_case or re.search(r'教程|案例|实例|示例|\b(?:example|tutorial|case)s?\b',query,re.I))
    wants_workflow=bool(re.search(r'步骤|顺序|流程|运行|初始化|\b(?:workflow|run|initializ\w*|steps?)\b',query,re.I))
    paths={}
    candidates={}

    def offer(doc, support=0., trace=None):
        if canonical_case and doc['case'] and doc['case']!=canonical_case:
            return
        did=doc['id']; score,matched=lexical.get(did,(0.,[]))
        # Relation boost is bounded; multiple paths never accumulate votes.
        rank=score/maximum+0.5*support
        key=doc['evidence']['path']
        old=candidates.get(key)
        item=(rank,score,doc,matched,support,trace)
        if old is None or (rank,score,did)>(old[0],old[1],old[2]['id']):
            candidates[key]=item

    for score,doc,matched in scores:
        offer(doc)

    def materialize(nid,support,trace):
        if nid in byid:
            offer(byid[nid],support,trace)
        elif nodes[nid]['kind']=='file':
            ds=byfile.get(nodes[nid]['path'],[])
            if ds:
                doc=max(ds,key=lambda d:(lexical.get(d['id'],(0,[]))[0],d['id']))
                offer(doc,support,trace)

    for hit in initial:
        hid=hit['id']; ev=hit['evidence']
        strength=max(0.,hit['score']/maximum)
        seeds=[hid]
        fid='file:'+ev['path']
        if fid in nodes:
            seeds.append(fid)
            for e in incoming[fid]:
                n=nodes[e['source']]
                if e['relation']=='DEFINED_IN' and n['line_start']<=ev['line_end'] and n['line_end']>=ev['line_start']:
                    seeds.append(n['id'])
        for seed in sorted(set(seeds)):
            queue=[(seed,[],strength,{seed})]
            while queue:
                nid,chain,support,visited=queue.pop(0)
                if len(chain)>=3:
                    continue
                choices=[]
                for e in outgoing[nid]:
                    relation=e['relation']
                    allowed=relation in {'REFERS_TO_DEFINITION','CONFLICTS_WITH','INCLUDES'}
                    if relation=='DOCUMENTED_ON':
                        allowed=bool(chain and chain[-1]['relation']=='REFERS_TO_DEFINITION')
                    if relation=='HAS_STEP':
                        allowed=wants_workflow or nodes[seed]['kind']=='script_step' or ev['path'].endswith('/Allrun')
                    if allowed:
                        choices.append((e,e['target'],'forward'))
                for e in incoming[nid]:
                    relation=e['relation']
                    allowed=relation=='CONFLICTS_WITH'
                    if relation=='DOCUMENTED_ON':
                        allowed=wants_examples and nodes[nid]['kind'] in {'manual_evidence', 'manual_page'} and not chain
                    if relation=='REFERS_TO_DEFINITION':
                        allowed=wants_examples and bool(chain and chain[-1]['relation']=='DOCUMENTED_ON')
                    if allowed:
                        choices.append((e,e['source'],'reverse'))
                for edge,target,direction in choices:
                    if target in visited:
                        continue
                    target_node=nodes[target]
                    if canonical_case and target_node.get('case') not in (None,canonical_case):
                        continue
                    relation=edge['relation']
                    factor=0.85
                    if relation=='CONFLICTS_WITH':
                        factor=1.
                    elif relation=='INCLUDES':
                        factor=0.7
                    elif relation=='DOCUMENTED_ON' and direction=='forward':
                        factor=1.
                    elif direction=='reverse':
                        # Penalize common definitions with many instances; do not use graph popularity as relevance.
                        degree=len({e['source'] for e in incoming[nid] if e['relation']==relation})
                        factor=0.65/math.sqrt(max(1,degree))
                    trace=chain+[{'relation':relation,'direction':direction,'source':edge['source'],
                                 'target':edge['target'],'evidence':edge['evidence'],'status':edge['status']}]
                    new_support=support*factor
                    provenance={'seed_document':hid,'seed_node':seed,'seed_evidence':ev,'edges':trace}
                    materialize(target,new_support,provenance)
                    queue.append((target,trace,new_support,visited|{target}))

    # Protect strongest lexical evidence. Unused expansion capacity is filled by lexical candidates.
    protected=[]; seen=set()
    for hit in initial:
        path=hit['evidence']['path']
        if path not in seen:
            protected.append(hit); seen.add(path)
        if len(protected)>=math.ceil(limit/2):
            break
    ranked=sorted(candidates.values(),key=lambda x:(-x[0],-x[1],x[2]['id']))
    def render(item):
        rank,score,doc,matched,support,trace=item
        result=make_result(score,doc,matched)
        result['ranking']={'lexical_normalized':round(score/maximum,6),'graph_support':round(support,6),
                           'combined':round(rank,6)}
        if trace:
            result['graph_path']=trace
        return result

    selected=[]
    for hit in protected:
        enriched=render(candidates[hit['evidence']['path']])
        enriched['ranking']['protected_lexical_file']=True
        selected.append(enriched)
    for rank,score,doc,matched,support,trace in ranked:
        if len(selected)>=limit:
            break
        path=doc['evidence']['path']
        if path in seen:
            continue
        result=render((rank,score,doc,matched,support,trace))
        selected.append(result);seen.add(path)
        if len(selected)>=limit:
            break
    for hit in selected:
        hit.setdefault('ranking',{'protected_lexical':True})
    related=[h for h in selected if 'graph_path' in h]
    edges=[]
    for hit in related:
        for e in hit['graph_path']['edges']:
            if e not in edges:
                edges.append(e)
    return selected,related,edges
