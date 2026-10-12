"""模型作用域下的双来源参数结构；不读取题集、不执行字典、不猜物理适用性。"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict, deque
import copy
import json
from pathlib import Path
import re

import knowledge as k
import manual_graph as m
import manual_parameters as p

SCHEMA='task-structure-v1'
MODES=('off','nodes','aligned','candidates')
# Slot/family names are structural vocabulary, not case names or question facts.
FAMILIES={
    'thermo':{'thermodynamic models'}, 'equationOfState':{'equation of states'},
    'transport':{'fluid transport','solid transport'},
    'activationModel':{'activation models'},'afterburnModel':{'afterburn models'},
    'diameterModel':{'diameter models'},'burstModel':{'burst models'},
    'radialModel':{'radial distribution models'},
    'fluxScheme':{'riemann solvers'},
}
THERMO_BLOCKS={'thermo':'thermodynamics','transport':'transport','equationOfState':'equationOfState'}


def title(value):
    return re.sub(r'^\d+(?:\.\d+)*\s*','',value).strip(' `')


def section_names(section):
    label=re.sub(r'\s*\[default\]\s*$','',title(section['label']),flags=re.I)
    # Slash-separated or parenthesized literal identifiers are explicit labels.
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*(?:/[A-Za-z][A-Za-z0-9_]*)*(?:\s+\([A-Za-z][A-Za-z0-9_]*\))?',label):
        return []
    return re.findall(r'[A-Za-z][A-Za-z0-9_]*',label)


def selector_family(entry):
    parts=entry['dictionary_path'].split('/')
    if entry['key']=='type' and parts[0]=='functions':return {'function objects'}
    if entry['key']=='type' and parts[0]=='boundaryField':return {'boundary conditions'}
    if entry['key']=='type' and len(parts)>1 and parts[-2]=='thermodynamics':return {'thermodynamic models'}
    if entry['key'] in FAMILIES:return FAMILIES[entry['key']]
    if entry['key'].endswith('Model'):
        # A literal camelCase slot may identify its documented plural family;
        # an absent family is not permission to match a globally unique word.
        stem=entry['key'][:-5]
        return {re.sub(r'(?<=[a-z0-9])([A-Z])',r' \1',stem).lower()+' models'}
    return None


def selectors(entries,manual):
    byname=defaultdict(list); pairs=[]; issues=[]
    canonical=lambda entry:(entry['evidence']['path'],re.sub(r'@\d+(?=/|$)','',entry['dictionary_path']))
    occurrences=Counter(canonical(entry) for entry in entries)
    for section in manual['nodes']:
        if section['kind']=='section':
            for name in section_names(section):byname[name].append(section)
    for entry in entries:
        key=entry['key']; parts=entry['dictionary_path'].split('/')
        eligible=(key in FAMILIES or key in {'type','model','fluxScheme','integrator'} or key.endswith('Model'))
        if not eligible or parts[0]=='FoamFile':continue
        if occurrences[canonical(entry)]>1:
            issues.append({'reason':'duplicate_selector_needs_override_resolution','configuration':entry['id'],'status':'unresolved'})
            continue
        value=entry['value'].strip('"')
        if not entry['resolved'] or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*',value):continue
        candidates=byname.get(value,[])
        family=selector_family(entry)
        if not family:
            if candidates:issues.append({'reason':'selector_factory_scope_not_established','configuration':entry['id'],
                'value':value,'sections':[s['id'] for s in candidates],'status':'unresolved'})
            continue
        candidates=[s for s in candidates if family & {title(h).casefold() for h in s['hierarchy'][:-1]}]
        if len(candidates)==1:
            pairs.append((entry,candidates[0]))
        elif candidates:
            issues.append({'reason':'ambiguous_model_section','configuration':entry['id'],'value':value,
                           'sections':[s['id'] for s in candidates],'status':'unresolved'})
    return pairs,issues


def directive_contexts(text):
    """Literal include placement only; list/macro scopes remain unresolved."""
    stream=k.lex(text); braces=[]; arrays=0; conditions=0; result={}
    for i,(word,start,end) in enumerate(stream):
        if word.startswith(('#if','#ifdef','#ifeq')):conditions+=1
        if word=='#endif':conditions=max(0,conditions-1)
        if word in ('(', '['):arrays+=1
        elif word in (')', ']'):arrays=max(0,arrays-1)
        elif word=='{':
            previous=stream[i-1][0].strip('"') if i else ''
            braces.append(previous if re.fullmatch(r'[A-Za-z][A-Za-z0-9_.:-]*',previous) else None)
        elif word=='}':
            if braces:braces.pop()
        elif word in ('#include','#includeIfPresent'):
            result[text.count('\n',0,start)+1]={'components':list(braces),'array_depth':arrays,
                'conditional_depth':conditions,'resolved_scope':not arrays and not conditions and None not in braces}
    return result


def scope_metadata(entry):
    ev=entry['evidence']; case=entry.get('case'); path=ev['path']; parts=entry['dictionary_path'].split('/')
    relative=path[len(case)+1:] if case and path.startswith(case+'/') else path
    location=relative.split('/')
    return {'case':case,'physical_file':path,'components':parts[:-1],'key':entry['key'],
            'region_directory_hint':location[1] if len(location)>2 and location[0] in ('system','constant','0','0.orig') else None,
            'field_file_hint':location[-1] if location[0] in ('0','0.orig') else None,
            'field_scope':'boundary' if parts[0]=='boundaryField' else 'internal' if parts[0]=='internalField' else None,
            'boundary':parts[1] if len(parts)>1 and parts[0]=='boundaryField' else None,
            'status':'physical_dictionary_scope_not_effective_override_resolution'}


def local_scope(selector,entry):
    """Require same physical file and explicit owner prefix; never same-case only."""
    if selector['evidence']['path']!=entry['evidence']['path']:return None
    selected=selector['dictionary_path'].split('/'); target=entry['dictionary_path'].split('/')[:-1]
    owner=selected[:-1]; key=selector['key']
    if len(owner)>0 and owner[-1]=='thermoType' and key in THERMO_BLOCKS:
        owner=owner[:-1]
        expected=owner+[THERMO_BLOCKS[key]]
        return 'same_owner_thermo_component' if target==expected else None
    if target==owner:return 'same_dictionary_block'
    # A model-named coefficient block explicitly repeats the selected model.
    if target in (owner+[selector['value']+'Coeffs'],owner+[selector['value']]):
        return 'model_named_coefficient_block'
    return None


def augment(skill,mode='aligned'):
    if mode not in MODES:raise ValueError('unknown structure mode')
    skill=Path(skill); corpus=skill/'corpus'; release=k.release_path(skill/'index')
    k.check_release(release,corpus)
    graph=copy.deepcopy(k.read_json(release/'graph.json'))
    docs=copy.deepcopy(k.read_json(release/'documents.json'))
    manifest=copy.deepcopy(k.read_json(release/'manifest.json'))
    base_snapshot=graph['snapshot']; original={n['id']:n for n in graph['nodes']}
    manual=m.build(corpus/'manual/markdown'); manual_nodes={n['id']:n for n in manual['nodes']}
    entries=[n for n in graph['nodes'] if n['kind']=='configuration']
    for entry in entries:
        entry.update(source_category='tutorial',evidence_status='tutorial_observed',instance_value=entry['value'],
                     scope=scope_metadata(entry),extraction_method='static_dictionary_parser',is_general_default=False)
    parameters=p.build(manual)['nodes'] if mode!='off' else []
    for node in parameters:
        graph['nodes'].append(node)
        docs.append({'id':node['id'],'text':node['raw_row'],'title':' '.join(node['hierarchy'])+' '+node['label'],
                     'evidence':node['evidence'],'case':None,'source_scope':'manual',
                     'terms':dict(Counter(k.tokens(' '.join(node['hierarchy'])+' '+node['raw_row'])))})
        graph['edges'].extend([
            {'source':node['section'],'target':node['id'],'relation':'HAS_PARAMETER_ROW','evidence':node['evidence'],'status':'manual_explicit'},
            {'source':node['id'],'target':node['evidence_unit'],'relation':'PARAMETER_CONTEXT','evidence':node['evidence'],'status':'same_section_original_table'}])
    pairs,issues=selectors(entries,manual)
    owner_selectors=Counter((n['evidence']['path'],n['dictionary_path'].rsplit('/',1)[0] if '/' in n['dictionary_path'] else '') for n,_ in pairs)
    config_byfile=defaultdict(list); params_bysection=defaultdict(list); includes=defaultdict(list)
    for entry in entries:config_byfile[entry['evidence']['path']].append(entry)
    for param in parameters:params_bysection[param['section']].append(param)
    for node in graph['nodes']:
        if node['kind']!='file':continue
        for evidence in node.get('dictionary_inclusion_evidence',[]):
            source=evidence['path']; contexts=directive_contexts((corpus/source).read_text())
            context=contexts.get(evidence['line_start'])
            if context:
                includes[source].append({'target':node['path'],'evidence':evidence,'context':context})
    alignments=[]; selector_records=[]
    for selector,section in pairs:
        sev={'path':'manual/markdown/'+section['path'],'sha256':section['sha256'],
             'line_start':section['start'],'line_end':section['start'],'section':section['label']}
        record={'selector':selector['id'],'section':section['id'],'model':selector['value'],
                'scope':selector['scope'],'evidence':[selector['evidence'],sev],
                'status':'deterministic_selector_and_section_identity_not_physics_validation'}
        selector_records.append(record)
        if mode not in ('aligned','candidates'):continue
        graph['edges'].append({'source':selector['id'],'target':section['id'],'relation':'SELECTS_DOCUMENTED_MODEL',
            'evidence':selector['evidence'],'supporting_evidence':[sev],'status':record['status']})
        for param in params_bysection[section['id']]:
            possible=[]
            for entry in config_byfile[selector['evidence']['path']]:
                context=local_scope(selector,entry)
                if context:possible.append((entry,context,[]))
            if mode=='candidates':
                # Include navigation is proven; applying a root thermo selector to
                # each included species remains a candidate, not an effective value.
                queue=deque([(selector['evidence']['path'],[])]); visited=set()
                while queue:
                    path,trail=queue.popleft()
                    if path in visited:continue
                    visited.add(path)
                    for link in includes.get(path,[]):
                        if not link['context']['resolved_scope'] or link['context']['components']:continue
                        proof=trail+[link['evidence']]; target=link['target']
                        queue.append((target,proof))
                        if selector['dictionary_path']!='thermoType/'+selector['key'] or selector['key'] not in THERMO_BLOCKS:continue
                        for entry in config_byfile[target]:
                            ep=entry['dictionary_path'].split('/')
                            if entry.get('case')==selector.get('case') and len(ep)>=2 and ep[-2]==THERMO_BLOCKS[selector['key']]:
                                possible.append((entry,'root_include_component_candidate',proof))
            for entry,context,trail in possible:
                names=[i for i in param['identifiers'] if i['name']==entry['key']]
                if not names:continue
                exact=[i for i in names if i['status']!='notation_normalization_candidate']
                selector_owner=selector['dictionary_path'].rsplit('/',1)[0] if '/' in selector['dictionary_path'] else ''
                shared_block=context=='same_dictionary_block' and owner_selectors[(selector['evidence']['path'],selector_owner)]>1
                candidate=not exact or bool(trail) or shared_block
                if candidate and mode!='candidates':continue
                if not entry['resolved'] or '@' in entry['dictionary_path']:continue
                status='scoped_candidate_needs_source_check' if candidate else 'deterministic_key_model_and_physical_scope_alignment'
                proof=[param['evidence'],selector['evidence'],sev,*trail,entry['evidence']]
                relation='PARAMETER_INSTANCE_CANDIDATE' if candidate else 'PARAMETER_INSTANCE'
                edge={'source':entry['id'],'target':param['id'],'relation':relation,'evidence':entry['evidence'],
                      'supporting_evidence':proof,'status':status,'scope':entry['scope'],
                      'selector':selector['id'],'match_rule':context,
                      'candidate_reasons':(['notation_normalization'] if not exact else [])+(['include_component_scope'] if trail else [])+(['shared_block_parameter_ownership_unresolved'] if shared_block else []),
                      'confidence':0.5 if candidate else 1.0,
                      'confidence_scope':'structural identity only; no claim of runtime selection, default value, dependency or physical compatibility'}
                graph['edges'].append(edge); alignments.append(edge)
    ids={n['id'] for n in graph['nodes']}
    if any(e['source'] not in ids or e['target'] not in ids for e in graph['edges']):
        raise ValueError('dangling task-structure edge')
    dependencies={name:k.digest(Path(__file__).with_name(name).read_bytes()) for name in ('task_structure.py','manual_parameters.py','manual_graph.py','knowledge.py')}
    graph['task_structure']={'schema':SCHEMA,'mode':mode,'parent_snapshot':base_snapshot,
        'dependencies':dependencies,'manual_snapshot':manual['snapshot'],'parameters':len(parameters),
        'selectors':selector_records,'alignments':len(alignments),'issues':issues,
        'status_counts':dict(Counter(e['status'] for e in alignments)),
        'limits':['Physical scope is not effective include/override execution.','A parameter instance never supplies a universal default.','Only direct section parameter ownership is used; parent conditions are not inherited unconditionally.']}
    graph['issues'].extend(issues)
    graph['snapshot']=k.digest(k.encoded({key:value for key,value in graph.items() if key!='snapshot'}))
    manifest.update(snapshot=graph['snapshot'],task_structure=graph['task_structure'],
                    tool_hash=k.digest(k.encoded(dependencies)))
    manifest['counts'].update(nodes=len(graph['nodes']),edges=len(graph['edges']),documents=len(docs))
    return graph,docs,manifest


def build(skill,mode):
    skill=Path(skill); graph,docs,manifest=augment(skill,mode)
    release=skill/'index/releases'/graph['snapshot']
    if release.exists():raise ValueError('use a fresh variant; preserve previous release')
    release.mkdir(parents=True)
    for name,value in [('graph.json',graph),('documents.json',docs),('manifest.json',manifest)]:k.write_json(release/name,value)
    k.check_release(release,skill/'corpus')
    k.write_json(skill/'index/current.json',{'snapshot':graph['snapshot']})
    return {'snapshot':graph['snapshot'],'counts':manifest['counts'],'structure':graph['task_structure']}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--skill',type=Path,required=True)
    parser.add_argument('--mode',choices=MODES,required=True)
    args=parser.parse_args();result=build(args.skill,args.mode)
    print(json.dumps({key:result[key] for key in ('snapshot','counts')}|{'parameters':result['structure']['parameters'],'alignments':result['structure']['alignments']},ensure_ascii=False))
