"""完整候选的物理身份、角色定义、有条件双侧关系与有界约束路径。

实体身份来自全语料物理位置和经核验的语义签名；同名仅产生候选，不能自行变成因果关系。
"""
from __future__ import annotations
import argparse
from collections import Counter,defaultdict
import json
from pathlib import Path,PurePosixPath
import posixpath
import re

import graphify_cross_source as cross
from candidate_graph_utils import sha,wire
from candidate_paths import Paths,SEMANTIC,STRUCTURAL


def anchors(node,index):
    result=[]
    for sid in node.get('source_span_ids',[]):
        a=index['spans'][sid]
        if a['kind']=='original_text_lines':
            result.append({'path':a['path'],'start':a['line_start'],'end':a['line_end'],'source_sha256':a['sha256']})
    return result


def normalized_node(n,index):
    metadata=n.get('metadata',{})
    return {'id':n['id'],'kind':n['structure_kind'],'label':n['label'],'scope':n['scope'],
            'path':n['source_file'],'evidence':anchors(n,index),'status':n['evidence_status'],
            'key':metadata.get('key'),'value':metadata.get('value_text'),
            'dictionary':metadata.get('dictionary_path'),'components':metadata.get('components',[]),
            'physical_components':metadata.get('physical_components',[]),'parent':metadata.get('parent_node') or metadata.get('parent_section'),
            'flags':metadata.get('flags',[]),'conditions':metadata.get('conditional_context',[]),
            'line_start':metadata.get('line_start'),'line_end':metadata.get('line_end'),
            'argument':metadata.get('argument_text'),'effective_state':'not_evaluated',
            # Literal source text is stored in the graph itself. Query-time
            # matching scans this field directly; no passage/vector/inverted index.
            'search_text':'\n'.join(str(value) for value in (
                n.get('label',''),n.get('rationale',''),metadata.get('key',''),
                metadata.get('value_text',''),metadata.get('dictionary_path',''),
                n.get('source_file','')) if value)}


def scoped_roles_match(instance,definition):
    """Role proof must include an observed selector key; a name alone is insufficient."""
    selectors=definition.get('selector_keys',[])
    parents=definition.get('parent_keys',[])
    if not selectors or instance['key'] not in selectors:
        return False
    return all(p in instance['components'][:-1] for p in parents)


def assertion_owners(assertion,definitions):
    # An explicit role cannot be discarded simply because the name is unique.
    candidates=[d for d in definitions if d['name']==assertion['subject']]
    role=assertion.get('subject_role')
    return [d for d in candidates if d['role']==role] if role else candidates


def include_target(path,arg,inventory):
    if not isinstance(arg,str) or not re.fullmatch(r'"[^"$<>]+"',arg.strip()):
        return None,'dynamic_or_non_literal_include'
    target=posixpath.normpath(str(PurePosixPath(path).parent)+'/'+arg.strip()[1:-1])
    if target.startswith('../') or target.startswith('/'):
        return None,'outside_corpus_include'
    if target not in inventory:
        return None,'include_target_absent'
    return target,None


def construct(structure,semantics):
    parent,parent_sha,raw_graph,index,raw,reads=cross.load_structure(structure)
    semantic=json.loads((semantics/'layer.json').read_text())
    if not semantic['complete']:
        raise ValueError('candidate requires complete applicable-source semantic coverage')
    if semantic['corpus_id']!=parent['corpus_id']:
        raise ValueError('semantic/physical corpus mismatch')
    nodes={n['id']:normalized_node(n,index) for n in raw_graph['nodes'] if n.get('_origin')=='principia_deterministic_structure'}
    edges=[];candidates=[];issues=[]
    for e in raw_graph['links']:
        if e.get('_origin')=='principia_deterministic_structure' and e.get('relation') in STRUCTURAL and e['source'] in nodes and e['target'] in nodes:
            edges.append({'source':e['source'],'target':e['target'],'relation':e['relation'],'status':'physical_structure',
                          'conditions':[],'evidence':nodes[e['target']]['evidence']})
    file_nodes={n['path']:n['id'] for n in nodes.values() if n['kind']=='file'}
    # Compare explicit README selector statements to a unique physical selector.
    # This records source disagreement, not which version was actually executed.
    selector_phrases={'activationModel':'activation model','equationOfState':'equation of state',
                      'fluxScheme':'flux scheme','thermodynamics':'thermodynamics model'}
    for readme in sorted(p for p in raw if PurePosixPath(p).name.lower()=='readme.md'):
        case=str(PurePosixPath(readme).parent)
        for key,phrase in selector_phrases.items():
            instances=[n for n in nodes.values() if n['kind']=='configuration' and n['key']==key
                       and n['scope'].get('case_directory')==case]
            if len(instances)!=1:continue
            n=instances[0]
            if not re.fullmatch(r'[A-Za-z_]\w*',n.get('value') or ''):continue
            pattern=r'(?:(?:uses|is activated using)\s+(?:the\s+)?([A-Za-z_]\w*)\s+'+re.escape(phrase)+r'|\b([A-Za-z_]\w*)\s+'+re.escape(phrase)+r'\s+is used\b)'
            for line,text in enumerate(raw[readme].decode().splitlines(),1):
                for match in re.finditer(pattern,text):
                    declared=match[1] or match[2]
                    if declared==n['value']:continue
                    original=[{'path':readme,'start':line,'end':line,'source_sha256':sha(raw[readme])}]
                    edges.append({'source':n['id'],'target':file_nodes[readme],'relation':'CONFLICTS_WITH',
                        'status':'explicit_source_values_disagree_version_and_execution_unresolved',
                        'conditions':['README temporal and conditional context remains in the original evidence'],
                        'condition_satisfied':None,'scope':n['scope'],'role':key,
                        'configured_value':n['value'],'documented_value':declared,
                        'instance_evidence':n['evidence'],'definition_evidence':original,
                        'evidence':n['evidence']+original})
    # Literal relative includes: no environment expansion, runtime code or implicit execution.
    include_edges=[]
    for n in list(nodes.values()):
        if n['kind']!='directive':continue
        if n['key'] not in ['#include','#includeIfPresent']:
            issues.append({'node':n['id'],'reason':'unsupported_directive_preserved_unresolved'});continue
        target,error=include_target(n['path'],n['argument'],raw)
        if error:
            issues.append({'node':n['id'],'reason':error,'optional':n['key']=='#includeIfPresent'});continue
        include_edges.append({'source':n['id'],'target':file_nodes[target],'relation':'INCLUDES',
             'status':'literal_include_context','conditions':n['conditions'],
             'evidence':n['evidence']+nodes[file_nodes[target]]['evidence'],
             'physical_origin':target,'effective_context':{'include_site':n['path'],'dictionary':n['dictionary']},
             'evaluates_overrides':False})
    file_adj=defaultdict(list)
    for e in include_edges:file_adj[nodes[e['source']]['path']].append(nodes[e['target']]['path'])
    def cycle(start,current,seen):
        if current==start:return True
        if current in seen:return False
        return any(cycle(start,next_file,seen|{current}) for next_file in file_adj[current])
    for e in include_edges:
        if cycle(nodes[e['source']]['path'],nodes[e['target']]['path'],set()):
            issues.append({'node':e['source'],'reason':'include_cycle_unresolved'})
            candidates.append({**e,'status':'unresolved_include_cycle'})
        else:edges.append(e)
    # A deliberately narrow static variable subset, with physical provenance retained.
    by_scope=defaultdict(list)
    for n in nodes.values():
        if n['kind']=='configuration':by_scope[n['path'],n['parent']].append(n)
    for rows in by_scope.values():
        for n in rows:
            value=n.get('value') or ''
            if '$' not in value:continue
            match=re.fullmatch(r'\$([A-Za-z_]\w*)',value.strip())
            matches=[p for p in rows if match and p['key']==match[1] and (p['line_start'] or 0)<(n['line_start'] or 0)]
            directives=[p for p in nodes.values() if p['path']==n['path'] and p['kind']=='directive']
            if len(matches)==1 and not directives and not n['conditions'] and '$' not in (matches[0]['value'] or ''):
                source=matches[0]
                edges.append({'source':n['id'],'target':source['id'],'relation':'STATIC_REFERS_TO',
                              'status':'literal_local_reference','conditions':[],
                              'evidence':n['evidence']+source['evidence'],'effective_value':source['value'],
                              'physical_origin':source['path'],'effective_context':n['dictionary']})
            else:issues.append({'node':n['id'],'reason':'variable_or_override_unresolved'})
    definitions=defaultdict(list)
    # Register the complete semantic layer before linking assertions.  Semantic
    # chunks from the same source can split a subject definition and its rule;
    # record-local lookup left those source-supported rules isolated.
    for record in semantic['records']:
        for d in record['definitions']:
            node={**d,'kind':'domain_definition','path':record['path'],'label':d['name']+' / '+d['role'],
                  'scope':{'corpus_version':parent['corpus_id'],'source_version':record['source_sha256'],'case_directory':None},
                  'status':'source_supported_definition'}
            nodes[d['id']]=node;definitions[d['name']].append(node)
            edges.append({'source':file_nodes[record['path']],'target':d['id'],'relation':'DECLARES','status':'source_supported',
                          'conditions':[],'evidence':d['evidence']})
    for record in semantic['records']:
        for assertion in record['assertions']:
            aid=assertion['id']
            nodes[aid]={**assertion,'kind':'conditional_assertion','path':record['path'],
                        'label':assertion['subject']+' '+assertion['predicate']+' '+assertion['object'],
                        'scope':{'corpus_version':parent['corpus_id'],'case_directory':None}}
            edges.append({'source':file_nodes[record['path']],'target':aid,'relation':'DECLARES',
                          'status':'source_supported_assertion','conditions':[],
                          'evidence':assertion['evidence']})
            possible=definitions.get(assertion['subject'],[])
            owners=assertion_owners(assertion,possible)
            if len(owners)!=1:
                candidates.append({'target':aid,'reason':'assertion_owner_ambiguous','owners':[d['id'] for d in owners]})
                # Exact subject spelling is useful navigation but does not
                # resolve a role disagreement or establish the predicate.
                for definition in possible:
                    edges.append({'source':aid,'target':definition['id'],'relation':'ASSERTION_SUBJECT',
                                  'status':'literal_subject_name_alignment_role_unresolved',
                                  'conditions':[],'condition_satisfied':None,
                                  'evidence':assertion['evidence']+definition['evidence']})
            else:
                edges.append({'source':owners[0]['id'],'target':aid,'relation':assertion['predicate'],
                              'status':'source_supported_declaration','conditions':[assertion['condition']] if assertion.get('condition') else [],
                              'condition_satisfied':None,'evidence':assertion['evidence']})
            targets=definitions.get(assertion['object'],[])
            if len(targets)==1 and (len(owners)!=1 or targets[0]['id']!=owners[0]['id']):
                edges.append({'source':aid,'target':targets[0]['id'],'relation':'ASSERTION_OBJECT',
                              'status':'unique_global_definition_name','conditions':[],
                              'evidence':assertion['evidence']+targets[0]['evidence']})
    # Add conservative lexical navigation edges.  These edges never claim
    # activation or semantic equivalence; they only bridge a literal physical
    # dictionary key to same-spelled documentation, or a documented model
    # input signature to a same-spelled physical entry.
    generic_keys={'type','field','value','name','model','active','enabled','object','class','format','location'}
    signature_definitions=defaultdict(list)
    for rows in definitions.values():
        for definition in rows:
            for name in definition.get('input_signature',[]):
                if isinstance(name,str):signature_definitions[name].append(definition)
    for n in list(nodes.values()):
        if n['kind']!='configuration' or not isinstance(n.get('key'),str):continue
        key=n['key']
        same_name=definitions.get(key,[])
        if len(key)>=3 and key.casefold() not in generic_keys and len(same_name)<=4:
            for definition in same_name:
                edges.append({'source':n['id'],'target':definition['id'],'relation':'LEXICALLY_ALIGNED_WITH',
                              'status':'literal_key_name_alignment_role_unresolved','conditions':[],
                              'condition_satisfied':None,'instance_evidence':n['evidence'],
                              'definition_evidence':definition['evidence'],
                              'evidence':n['evidence']+definition['evidence']})
        for definition in signature_definitions.get(key,[]):
            edges.append({'source':n['id'],'target':definition['id'],'relation':'INPUT_SIGNATURE_MATCH',
                          'status':'literal_key_in_documented_input_signature_not_runtime_activation',
                          'conditions':[],'condition_satisfied':None,'instance_evidence':n['evidence'],
                          'definition_evidence':definition['evidence'],
                          'evidence':n['evidence']+definition['evidence']})
    # Both physical selection and role-specific definition evidence are mandatory.
    for n in list(nodes.values()):
        if n['kind']!='configuration' or not n.get('value'):continue
        names=set(re.findall(r'[A-Za-z_]\w*',n['value']))
        for name in names & definitions.keys():
            possible=definitions[name]
            compatible=[d for d in possible if scoped_roles_match(n,d)]
            for d in possible:
                relation={'source':n['id'],'target':d['id'],'relation':'DOCUMENTED_BY',
                          'instance_evidence':n['evidence'],'definition_evidence':d['evidence'],
                          'evidence':n['evidence']+d['evidence'],'conditions':n['conditions'],
                          'condition_satisfied':None,'role':d['role'],'scope':n['scope'],
                          'status':'literal_role_matched_alignment_not_runtime_activation'}
                if d in compatible and n['evidence'] and d['evidence'] and not n['flags']:
                    edges.append(relation)
                else:candidates.append({**relation,'status':'unresolved_role_or_selector'})
    for idx,e in enumerate(edges):e['id']='candidate.edge:'+sha(e)[:24]
    return {'schema':'candidate-conditional-graph-v1','corpus_id':parent['corpus_id'],
            'structure_manifest_sha256':parent_sha,'semantic_layer_sha256':sha((semantics/'layer.json').read_bytes()),
            'nodes':nodes,'edges':edges,'candidates':candidates,'issues':issues,
            'coverage':{'inventory_files':len(raw),'physical_nodes':sum(n['kind'] not in ['domain_definition','conditional_assertion'] for n in nodes.values()),
                        'semantic_files':len(semantic['coverage']),'semantic_complete':semantic['complete']},
            'construction_accounting':reads,'source_code_sha256':sha(Path(__file__).read_bytes())}


if __name__=='__main__':
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--structure',type=Path,required=True);cli.add_argument('--semantics',type=Path,required=True)
    cli.add_argument('--output',type=Path,required=True);args=cli.parse_args()
    if args.output.exists():raise FileExistsError('preserve candidate graph')
    graph=construct(args.structure.resolve(),args.semantics.resolve())
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(wire(graph))
    print(wire({'nodes':len(graph['nodes']),'edges':len(graph['edges']),'candidates':len(graph['candidates']),'coverage':graph['coverage']}))
