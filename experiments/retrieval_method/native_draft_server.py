"""Experimental locator projection: source-linked edits, same shared editor."""
import copy
from decimal import Decimal
import json
from pathlib import Path
import re
from mcp_servers.principia_retrieval import knowledge_navigation, server
from experiments.retrieval_method.model_edit_draft import draft_model_edits
from experiments.retrieval_method.attribute_target import LABEL, PREDICATE, resolve_target, selector_text
from experiments.retrieval_method.dependency_edit_draft import draft_dependency_edits
from experiments.retrieval_method.removal_intent import requested_removals


def projected_requirement_sources(condition,draft):
    """Omit exclusive replacement evidence for explicitly preserved targets only."""
    omitted=set();needed=set()
    for req in condition.get('requirements',[]):
        states=[s for s in draft.get('target_states',[]) if s['path']==req['target']]
        preserved=(states and all(s['state']=='present_preserved' for s in states)
                   and not any(e['path']==req['target'] for e in draft['edits']))
        (omitted if preserved else needed).update(req.get('support',[]))
    return [s for s in condition['code_sources'] if s['id'] not in omitted-needed]


def excluded_proposed_condition(search,packet,condition,edits):
    """Use the existing reviewed zero-input predicate on a labelled proposal."""
    rule=next(r for r in search.rules if r['id']==condition['id'])
    binding=rule.get('state_binding',{})
    if binding.get('predicate')!='explicit_const_zero_excludes_viscosity':return None
    root=search.engine.skill/'corpus'/packet['case']
    assessment=search.assess_case(root,packet['case'],budget=12000)
    observed=next((c for c in assessment['conditions'] if c['id']==condition['id']),None)
    if not observed or not observed.get('application_check',{}).get('matches_reviewed_application'):return None
    from case_state import viscosity_state
    proposed=viscosity_state(root,edits)
    if proposed['state']!='all_const_zero':return None
    return {'id':condition['id'],'condition_evaluation':'inactive_for_proposed_inputs',
            'preparation_edits':[],'state_source_sha256':proposed['sha256'],
            'state_scope':'Source template plus proposed edits; all const mu=0. Recheck the actual copy.',
            'binding_sources':[{k:v for k,v in ev.items() if k in ('path','start','end')} for ev in binding['evidence']]}


def explicit_inputs(search, packet, text):
    from edit_graph import edit_intent_text
    text=edit_intent_text(text)
    values={}
    for location in packet['locations']:
        node=search.search.nodes[location['id']]
        if node['kind']!='input_schema':continue
        for entry in node['entries']:
            key=entry['entry'].rsplit('/',1)[-1]
            matches=re.findall(r'(?<![A-Za-z0-9_/])'+re.escape(key)+r'\s*(?:[=:：]|设置为|设为|取值为|为|\bis\b|\bto\b)\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)(?![A-Za-z0-9_.])',text)
            if matches and len({Decimal(x) for x in matches})==1:values[key]=matches[0]
    return values


def locate_drafts(query,tutorial_case,translation='',budget=5000):
    if type(budget)!=int or not 1000<=budget<=24000:raise ValueError('budget must be 1000..24000')
    search=knowledge_navigation.navigator()
    text=query+'\n'+translation
    target=resolve_target(search.engine,tutorial_case,text) if re.search(LABEL,text,re.I) else None
    if not target:return _locate_drafts(search,query,tutorial_case,translation,budget,None)
    case='tutorials/'+tutorial_case.removeprefix('tutorials/')
    case=search.engine.graph.get('aliases',{}).get(case,case)
    proof={k:v for k,v in target.items() if k not in ('observed','matches')}
    proof['match_count']=len(target.get('matches',[]))
    if target['status']=='unique':
        proof['entry']=next(x['entry'] for x in target['observed'] if x['phase']==target['phase'])
    fallback={'status':'target_unresolved','case':case,'locations':[],
              'target_resolution':proof,'limits':'No edits proposed; resolve the target or request more evidence.'}
    wire=lambda p:len(json.dumps(p,ensure_ascii=False,separators=(',',':')))
    if wire(fallback)>budget:return {'status':'target_unresolved','locations':[],'limits':'Target evidence exceeds budget; no edits proposed.'}
    if target['status']!='unique':return fallback
    # A resolved property is an object constraint, not an edit destination.
    # Keep its evidence in the response, replacing only the resolved predicate
    # in the ranking text so gamma does not displace the transport destination.
    query=PREDICATE.sub(target['phase'],selector_text(query))
    translation=PREDICATE.sub(target['phase'],selector_text(translation))+'\n'+target['phase']
    packet=copy.deepcopy(_locate_drafts(search,query,tutorial_case,translation,budget,target))
    packet['target_resolution']=proof
    while wire(packet)>budget:
        excerpts=[x for x in packet.get('locations',[]) if x.get('text')]
        if not excerpts:return fallback
        item=max(excerpts,key=lambda x:len(x['text']))
        item['text']=item['text'][:-min(len(item['text']),wire(packet)-budget+20)]
        item['complete']=False
    return packet


def _locate_drafts(search,query,tutorial_case,translation,budget,target):
    # Resolve connected edit evidence before imposing the final response budget.
    # Otherwise condition prose can evict an input-schema node before drafting.
    packet=search.locate(query,tutorial_case,translation=translation,budget=max(budget,12000))
    fallback=lambda:search.locate(query,tutorial_case,translation=translation,budget=budget)
    model=draft_model_edits(search.search,packet,explicit_inputs(search,packet,query+'\n'+translation))
    if target and model.get('edits') and any(not e['entry'].startswith(target['phase']+'/') for e in model['edits']):
        return {'status':'target_not_located','case':packet['case'],'locations':[], 'limits':'Resolved object was not bound to an edit scope; no edits proposed.'}
    if model['status']=='missing_inputs':
        candidate={**packet,'limits':'Located scopes only; no edits or compatibility guarantee.','status':'located_missing_inputs','input_request':{'keys':model['missing_inputs'],'reason':'Missing or conflicting finite values; none inferred.'}}
        if len(json.dumps(candidate,ensure_ascii=False,separators=(',',':')))<=budget:return candidate
    if model['status']!='draft_requires_review':return fallback()
    coefficients=search.search.nodes[model['support']['coefficient_node']]
    selector=search.search.nodes[model['support']['selector_node']]
    current=next((e['value'] for e in selector.get('entries',[]) if e['entry']==model['edits'][0]['entry']),None)
    aliases={'mu':['固定黏度','固定粘度']} if current=='const' and coefficients['scope'].endswith('/transport') else {}
    keys=[e['entry'].rsplit('/',1)[-1] for e in coefficients.get('entries',[])]
    removals=requested_removals(query+'\n'+translation,coefficients['scope'],keys,aliases)
    if removals['status']=='resolved' and removals['keys']:
        model=draft_model_edits(search.search,packet,explicit_inputs(search,packet,query+'\n'+translation),removals['keys'])
    if removals['status']!='resolved' or model['status']!='draft_requires_review':
        return {'case':packet['case'],'status':removals['status'] if removals['status']!='resolved' else model['status'],
                'locations':[],'limits':'Requested removals need source/target/conflict review; no edits proposed.'}
    bindings=json.loads(Path(__file__).with_name('dependency_edit_bindings.json').read_text())
    conditionals=[]
    for condition in packet.get('conditions',[]):
        excluded=excluded_proposed_condition(search,packet,condition,model['edits'])
        if excluded:
            conditionals.append(excluded);continue
        draft=draft_dependency_edits(search,packet,[condition['id']],bindings)
        if not draft['edits'] and not draft.get('target_states'):continue
        conditionals.append({'id':condition['id'],'when':condition['when'],
                             'condition_evaluation':condition.get('condition_evaluation','not_evaluated'),
                             **({'preparation':condition['preparation'],'preparation_edits':draft['edits']}
                                if condition.get('preparation') else {'edits_if_true':draft['edits']}),
                             'target_states':[{k:v for k,v in x.items() if k not in ('sha256','via')} for x in draft.get('target_states',[]) if x['state'] in ('present_preserved','unresolved')],
                             'defaults':[r for r in condition.get('requirements',[]) if r.get('relation')=='DEFAULTS_WHEN'],
                             'state_scope':'Preserved ≠ validated.',
                             'example_sources':[{k:v for k,v in s.items() if k not in ('rule','sha256')} for s in draft['support']],
                             'requirement_sources':projected_requirement_sources(condition,draft)})
    result={k:packet[k] for k in ('case','snapshot','condition_snapshot','locations') if k in packet}
    result['locations']=[x for x in packet['locations'] if x['id'] in model['support'].values()]
    model.pop('remaining',None)
    result.update(status='conditional_edit_drafts',model_draft=model,
                  conditional_drafts=conditionals,binding_snapshot=bindings['snapshot'],
                  limits='草案未执行；核对参考设置和旧键/继承项。配置准备不证明运行激活。')
    result=copy.deepcopy(result)
    wire=lambda p:len(json.dumps(p,ensure_ascii=False,separators=(',',':')))
    while wire(result)>budget:
        excerpts=[x for x in result.get('locations',[]) if x.get('text')]
        if not excerpts:return fallback()
        item=max(excerpts,key=lambda x:len(x['text']))
        item['text']=item['text'][:-min(len(item['text']),wire(result)-budget+20)]
        item['complete']=False
    return result


def main():
    knowledge_navigation.locate=locate_drafts
    server.main()


if __name__=='__main__':main()
