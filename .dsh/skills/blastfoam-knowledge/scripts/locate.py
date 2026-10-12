"""Bounded task locator with source-backed conditions and bidirectional discovery."""
import argparse
from collections import Counter, defaultdict
import math
import re
from pathlib import Path

import evidence_bundle as b
import domain_graph as d


def fact_candidates(domain, chosen, query_terms, combined):
    """Surface reviewed ancestor conditions without asserting they apply to the task."""
    metadata=domain['metadata']
    sections={metadata[u]['section'] for u in chosen if u in metadata}
    ancestors={a for u in chosen for a in metadata.get(u,{}).get('ancestors',[])}
    candidates=[]
    for f in domain['facts']:
        named=d.named(f['subject']['name'],combined)
        names=f['subject']['name']+' '+f['object']['name']
        name_tokens=set(b.k.tokens(names))
        # An ancestor is a possible scope, not a license to import sibling facts.
        inherited=f['section'] in ancestors and any(t in name_tokens for t in query_terms)
        if not named and f['section'] not in sections and not inherited:continue
        text=names+' '+f['summary_zh']+' '+f['conditions_zh']
        tokens=set(b.k.tokens(text))
        relevance=sum(weight for t,weight in query_terms.items() if t in tokens)
        constraint=f['relation'] in ('LIMITED_TO','HAS_CONDITION','CONFLICTS_WITH','REQUIRES_INPUT')
        candidates.append((relevance+2*named+3*constraint,f))
    return sorted(candidates,key=lambda x:(-x[0],x[1]['id']))


def locate(engine, query, budget=3000, case=None, translation='', graph=True, domain=None):
    if type(budget) is not int or not 1000 <= budget <= 24000:
        raise ValueError('character budget must be 1000..24000')
    if not isinstance(query, str) or not query.strip() or len(query)>32768:
        raise ValueError('original query must contain 1..32768 characters')
    if not isinstance(translation, str) or len(translation)>32768:
        raise ValueError('translation must be text, at most 32768 characters')
    engine.validate()
    if domain is None:
        if not hasattr(engine,'_locator_domain'):engine._locator_domain=d.build(engine)
        domain=engine._locator_domain
    d.validate(domain,engine)
    combined=query+'\n'+translation;q=engine.query_terms(combined)
    wants_case=bool(re.search(r'教程|例子|案例|算例|tutorial|example|reference case|starting case',query,re.I))
    # Explicit paths outrank ambiguous basename matches. Do not silently select a solver.
    if case:
        canonical='tutorials/'+case.removeprefix('tutorials/')
        canonical=engine.graph['aliases'].get(canonical,canonical)
        if canonical not in engine.graph['cases']:raise ValueError('case_unavailable')
        matches=[canonical]
    else:
        full=[c for c in engine.graph['cases'] if d.named(c,combined) or d.named(c.removeprefix('tutorials/'),combined)]
        matches=full or [c for c in engine.graph['cases'] if d.named(Path(c).name,combined)]
        matches=sorted(set(matches))
    metadata=domain['metadata']
    scores={};exact={}
    for uid,tf in engine.terms.items():
        u=engine.units[uid]
        if matches and u['case'] not in (None,*matches):continue
        length=sum(tf.values());score=0.
        for term,weight in q.items():
            count=tf[term]
            if count:
                idf=math.log(1+(len(engine.units)-engine.df[term]+.5)/(engine.df[term]+.5))
                score+=weight*idf*count*2.2/(count+1.2*(.25+.75*length/engine.avg))
        meta=metadata.get(uid,{})
        label=meta.get('name','')
        exact[uid]=bool(label and d.named(label,combined)) or any(d.named(match.group(1),combined) for match in re.finditer(r'\b(?:type|[A-Za-z]\w*Model)\s+([A-Za-z]\w*)\s*;',engine.raw(u)))
        score+=sum(w for t,w in q.items() if t in b.k.tokens(u['path']+' '+meta.get('title',u['label'])))
        if exact[uid]:score+=20 if d.named(label,query) else 5
        if wants_case and 'overview' in u['roles'] and score>0:score=score*1.5+15
        if matches and u['case'] in matches:score+=20
        if score>0:scores[uid]=score
    ranked=sorted(scores,key=lambda uid:(-scores[uid],engine.units[uid]['path'],engine.units[uid]['start']))
    roots=[];seen_sections=set()
    # Preserve one candidate per explicitly named case before general ranking.
    for c in matches:
        found=next((uid for uid in ranked if engine.units[uid]['case']==c),None)
        if found:roots.append(found)
    for uid in ranked:
        meta=metadata.get(uid,{})
        section=meta.get('section')
        if uid in roots or (section and section in seen_sections):continue
        roots.append(uid)
        if section:seen_sections.add(section)
        if len(roots)>=3:break
    roots=roots[:3]
    result={'status':'ok' if roots else 'no_match','snapshot':engine.graph['snapshot'],
        'domain_snapshot':domain['snapshot'],'semantic_facts_available':len(domain['facts']),'matched_cases':matches[:3],'locations':[],'relations':[],'facts':[],
        'limits':'Preview may be partial. Facts retain source conditions; navigation direction does not reverse a claim. No match is not absence.'}
    chosen={};spans=defaultdict(set)
    def add(uid,reason):
        if uid in chosen:return chosen[uid]
        u=engine.units[uid];positions=set(range(u['start'],u['end']+1))
        if positions & spans[u['path']]:return None
        lid='L'+str(len(chosen)+1);raw=engine.raw(u);preview=raw[:320]
        item={'id':lid,'path':u['path'],'start':u['start'],'end':u['end'],
            'reason':reason,'title':metadata.get(uid,{}).get('title',u['label'])[:140],
            'preview':preview,'preview_complete':len(preview)==len(raw)}
        proposal={**result,'locations':result['locations']+[item]}
        if len(b.wire(proposal))>budget:return None
        result.update(proposal);chosen[uid]=lid;spans[u['path']].update(positions)
        return lid
    for uid in roots:add(uid,'explicit_entity' if exact.get(uid) else 'query_match')
    selected_facts=[]
    if graph:
        for _,f in fact_candidates(domain,chosen,q,combined):
            item={'id':f['id'],'subject':f['subject']['name'],'relation':f['relation'],
                'object':f['object']['name'],'conditions':f['conditions_zh'],
                'evidence':f['evidence'],'review':f['review'],
                'scope_note':'Check subject and conditions against the task; ancestor context is not universal applicability.'}
            proposal={**result,'facts':result['facts']+[item]}
            if len(b.wire(proposal))<=budget:
                result.update(proposal);selected_facts.append(f['id'])
            if len(selected_facts)>=3:break
    adj=defaultdict(list)
    all_edges=engine.graph['edges']+domain['edges']
    for edge in all_edges:
        adj[edge['source']].append((edge['target'],edge,'forward'))
        adj[edge['target']].append((edge['source'],edge,'reverse'))
    selected_edges=[]
    if graph:
        # Two hops, relevance gates, and no logical inversion of directed claims.
        frontier=list(chosen);visited=set(frontier)
        for hop in range(2):
            candidates=[]
            for uid in frontier:
                for dst,edge,direction in adj[uid]:
                    u=engine.units[dst]
                    if matches and u['case'] not in (None,*matches):continue
                    meta=metadata.get(dst,{})
                    rel=sum(w for t,w in q.items() if t in engine.terms[dst] or t in b.k.tokens(meta.get('title','')))
                    if edge['relation']=='CASE_SCRIPT_CONTEXT':
                        if not any(r in ('workflow','geometry','initialization') and re.search(p,combined,re.I) for r,p in b.ROLE_TERMS.items()):continue
                    essential=edge['relation'] in ('CONFLICTS_WITH','PARENT_CONTEXT','SECTION_CONTEXT','REFERS_TO_SECTION','REFERS_TO_FORMULA','ENTITY_DEFINITION','REFERS_TO_DEFINITION','SEPARATE_OUTPUT_CONTROLS')
                    if rel<=0 and not essential:continue
                    candidates.append((rel+3*essential,uid,dst,edge,direction))
            frontier=[]
            for _,src,dst,edge,direction in sorted(candidates,key=lambda x:(-x[0],b.wire(x[3]),x[4])):
                if edge in selected_edges or len(selected_edges)>=3:continue
                old=list(result['locations']);old_chosen=dict(chosen);old_spans={p:set(s) for p,s in spans.items()}
                lid=add(dst,'linked_source')
                if lid is None:continue
                item={'from':chosen[src],'to':lid,'type':edge['relation'],'traversal':direction,'status':edge['status']}
                proposal={**result,'relations':result['relations']+[item]}
                if len(b.wire(proposal))<=budget:
                    result.update(proposal);selected_edges.append(edge)
                    if dst not in visited:frontier.append(dst);visited.add(dst)
                else:
                    result['locations']=old;chosen.clear();chosen.update(old_chosen);spans.clear();spans.update(old_spans)
    if roots and not result['locations']:result['status']='budget_too_small'
    audit={'original_query':query,'translation':translation,'graph_enabled':graph,'matched_cases':matches,
        'characters':len(b.wire(result)),'selected_units':list(chosen),'selected_facts':selected_facts,
        'source_hashes':{engine.units[u]['path']:engine.graph['inventory'][engine.units[u]['path']] for u in chosen},
        'relations':selected_edges,'coverage':domain['coverage']}
    return result,audit


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--query',required=True);parser.add_argument('--translation',default='')
    parser.add_argument('--case');parser.add_argument('--budget',type=int,default=3000)
    parser.add_argument('--index',type=Path);parser.add_argument('--domain-index',type=Path)
    parser.add_argument('--audit',type=Path);parser.add_argument('--text-only',action='store_true')
    args=parser.parse_args();engine=b.EvidenceSearch(b.k.read_json(args.index) if args.index else None)
    domain=b.k.read_json(args.domain_index) if args.domain_index else None
    packet,audit=locate(engine,args.query,args.budget,args.case,args.translation,not args.text_only,domain)
    if args.audit:b.k.write_json(args.audit,audit)
    print(b.wire(packet))


if __name__=='__main__':main()
