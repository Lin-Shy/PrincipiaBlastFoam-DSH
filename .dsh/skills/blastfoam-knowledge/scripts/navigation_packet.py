"""Project graph evidence into a bounded, citable edit-navigation packet."""
import re
import evidence_bundle as b
from condition_graph import validate, example_differences


def build(search, original, case, translation='', budget=5000):
    # Ranking and source validation remain in the existing graph implementation.
    rich=search.locate(original,case,translation=translation,budget=24000)
    combined=original+'\n'+translation
    def named(name):
        return len(name)>1 and re.search(r'(?<![A-Za-z0-9_])'+re.escape(name)+r'(?![A-Za-z0-9_])',combined,re.I)
    result={'status':'ok','case':rich['case'],'snapshot':rich['snapshot'],
            'condition_snapshot':search.index['snapshot'],
            'scope':'indexed template, not edited files; values are current, not proposed',
            'source_semantics':'quotes are verbatim excerpts; null means omitted for budget',
            'locations':[],'conditions':[],'sources':[],'omitted':[]}
    sources={}
    def source(ev):
        key=(ev['path'],ev['start'],ev['end'])
        if key not in sources:
            ref='S'+str(len(sources)+1);sources[key]=ref
            result['sources'].append({'id':ref,'path':ev['path'],'start':ev['start'],'end':ev['end'],
                                      'quote':ev['quote']})
        return sources[key]
    roots=rich['locations'][:2]
    for location in roots:
        node=search.search.nodes[location['id']]
        entries=node['entries']
        selected=[e for e in entries if named(e['entry'].split('/')[-1])]
        if len(entries)>6 and selected:entries=selected
        item={'path':node['path'],'dictionary':node['scope'],
              'start':node['start'],'end':node['end'],
              'values':{e['entry']:e['value'] for e in entries}}
        result['locations'].append(item)
        # Include only the exact selector that owns this coefficient group.
        for dst,edge,direction in search.search.adj[node['id']]:
            if edge['relation']!='SELECTOR_COEFFICIENTS' or direction!='reverse':continue
            selector=search.search.nodes[dst]
            match=next(e for e in selector['entries'] if e['entry']==edge['selector_entry'])
            item.setdefault('selectors',[]).append({'entry':match['entry'],'value':match['value'],
                                                  'start':match['start'],'end':match['end']})
    # ConditionalEditSearch already binds returned rules to its first two roots.
    matched={c['id'] for c in rich.get('conditions',[])}
    for rule in validate(search.index,search.engine):
        if rule['id'] not in matched:continue
        item={'id':rule['id'],'when':rule['when'],'evaluation':'not_evaluated',
              'review':'author_reviewed','scope':rule.get('requirements_scope'),
              'required_files':rule['required_files'],'file_semantics':rule['required_files_semantics'],
              'support':[source(ev) for ev in rule['evidence']],
              'requirements':[],'examples':[]}
        for req in rule.get('requirements',[]):
            item['requirements'].append({k:v for k,v in req.items() if k!='evidence'} |
                                        {'support':[source(ev) for ev in req['evidence']]})
        examples={ev['path']:ev for ev in rule.get('examples',[])}
        for diff in example_differences(rule,search.engine,rich['case']):
            ev=examples[diff['example']]
            # Parsed values are a compact view of the reviewed example, not a
            # declaration that every absent exact key must be added.
            item['examples'].append({'target':diff['target'],'source':source(ev),
                'missing_exact':{e['entry']:e['example_value'] for e in diff['entries'] if e['target_value'] is None},
                'different_exact':{e['entry']:[e['target_value'],e['example_value']] for e in diff['entries'] if e['target_value'] is not None}})
        item['example_semantics']='exact-key differences, not required edits; patterns/includes unresolved'
        result['conditions'].append(item)
    # Model definitions are adjacent through selector identity, not guessed names.
    for location in roots:
        for dst,edge,direction in search.search.adj[location['id']]:
            if edge['relation']!='DOCUMENTED_COEFFICIENTS' or direction!='forward':continue
            node=search.search.nodes[dst]
            ev={'path':node['path'],'start':node['start'],'end':node['end'],'quote':search.search.raw(node)}
            ref=source(ev)
            result['locations'][roots.index(location)].setdefault('definition_sources',[]).append(ref)
    # Preserve paths/values and evidence addresses before raw excerpts. Never
    # silently pretend omitted evidence or condition rules were returned.
    def prune_sources():
        refs=set()
        def visit(value):
            if isinstance(value,list):
                for child in value:visit(child)
            elif isinstance(value,dict):
                for key,child in value.items():
                    if key in ('support','definition_sources'):refs.update(child)
                    elif key=='source':refs.add(child)
                    else:visit(child)
        visit(result['locations']);visit(result['conditions'])
        result['sources'][:]=[s for s in result['sources'] if s['id'] in refs]
    while len(b.wire(result))>budget:
        result['status']='partial'
        candidates=[s for s in result['sources'] if s['quote'] is not None]
        if candidates:
            example_refs={e['source'] for c in result['conditions'] for e in c['examples']}
            largest=max(candidates,key=lambda s:(s['id'] in example_refs,len(s['quote'])))
            largest['quote']=None
            continue
        if result['conditions']:
            removed=result['conditions'].pop();result['omitted'].append('condition:'+removed['id'])
            prune_sources()
            continue
        if result['locations']:
            removed=result['locations'].pop();result['omitted'].append('location:'+removed['path']+':'+removed['dictionary'])
            prune_sources()
            continue
        return {'status':'insufficient_budget','case':rich['case']}
    result['status']='partial' if result['omitted'] or any(s['quote'] is None for s in result['sources']) else 'ok'
    # Status is included in the enforced wire budget.
    if len(b.wire(result))>budget:
        return {'status':'insufficient_budget','case':rich['case']}
    return result
