"""Compile source-owned, verified semantics and conservative typed links."""
import argparse
from collections import defaultdict,Counter
import copy
import json
from pathlib import Path
import re
import sys

PROJECT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(PROJECT/'src'))
from principia_core.retrieval.knowledge_qa import FrozenKnowledgeCorpus
from chapter2_graph_sources import identity
from chapter2_offline_dataset_calls import read,save,sha,wire,MODEL
from chapter2_graph_semantics import accepted_semantics,curate_extraction,validate_verification

SELECTOR_ROLES={'equationOfState':'equation_of_state','thermo':'thermo_model',
 'transport':'transport_model','activationModel':'activation_model',
 'afterburnModel':'afterburn_model','errorEstimator':'error_estimator',
 'fluxScheme':'flux_scheme','timeIntegrator':'time_integrator','limiter':'limiter'}
PARAMETER_ROLES={'equationOfState':'equation_of_state','thermodynamics':'thermo_model',
 'transport':'transport_model','initiation':'activation_model'}

def public_name(value):
    # Case folding only; mathematical symbols, underscores and role distinctions
    # are not removed to force a match between different public identifiers.
    return str(value).strip().strip('"').casefold()

def literal_identifier(value):
    value=str(value).strip().strip('"')
    return value if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_<>.-]*',value) else None

def selector_role(node):
    parts=node.get('components',[]);key=node.get('key')
    if key in SELECTOR_ROLES:return SELECTOR_ROLES[key]
    if key!='type':return None
    if parts and parts[0]=='functions':return 'function_object'
    if 'boundaryField' in parts:return 'boundary_condition'
    if 'thermoType' in parts:return 'thermodynamic_class'
    if node['path'].endswith('/phaseProperties') and len(parts)<=2:return 'thermodynamic_class'
    return None

def physical_prefix(node,drop=1):
    return tuple((v['key'],v['occurrence']) for v in node.get('physical_components',[])[:-drop])

def compile_graph(source,records,source_hashes,*,complete,binding):
    graph=copy.deepcopy(source);nodes=graph['nodes'];edges=graph['edges'];units=graph['units']
    diagnostics=[];edge_ids={e['id'] for e in edges}
    def edge(a,b,relation,conditions=(),support=None):
        if a==b:return
        eid=identity('edge',a,b,relation)
        if eid in edge_ids:return
        edge_ids.add(eid)
        edges.append({'id':eid,'source':a,'target':b,'relation':relation,
          'conditions':list(conditions),'support':support or {},
          'status':'source_supported_not_execution'})
    definitions=[];facts=[];quarantined=[]
    for record in records:
        unit=units[record['unit_id']];local={}
        if any(re.fullmatch(r'(?:table of )?contents|目录',c['title'].strip(),re.I) for c in unit['context']):
            quarantined.append({'unit_id':unit['id'],'path':unit['path'],'start':unit['start'],'end':unit['end'],
              'reason':'Table-of-contents entries are navigation labels, not substantive model definitions. Chunk-local list headings can misassign roles.',
              'definitions_not_linked':len(record['accepted']['definitions']),'facts_not_linked':len(record['accepted']['facts'])})
            continue
        for kind in ('definitions','facts'):
            for row in record['accepted'][kind]:
                nid=identity('semantic',unit['id'],kind,row['id']);local[row['id']]=nid
                node={**row,'local_id':row['id'],'id':nid,'kind':'domain_definition' if kind=='definitions' else 'domain_fact',
                  'owner':unit['owner'],'unit_id':unit['id'],'path':unit['path'],
                  'label':row.get('name',row.get('subject')),'state':'verified_source_statement_not_execution'}
                nodes[nid]=node
                (definitions if kind=='definitions' else facts).append(node)
                edge(nid,identity('raw',unit['id']),'GROUNDED_IN',support={'evidence':row['evidence']})
        for row in record['accepted']['relations']:
            edge(local[row['source']],local[row['target']],row['relation'],row['conditions'],{'evidence':row['evidence']})
    # Public identity groups are source-owned nodes plus explicit edges. There
    # is deliberately no globally shared entity that can bypass an ablation.
    by_name=defaultdict(list)
    for d in definitions:
        for name in {d['name'],*d['aliases']}:
            if literal_identifier(name):by_name[public_name(name)].append(d)
    def candidates(name,role=None,selectors=None,owner=None):
        rows=list({d['id']:d for d in by_name.get(public_name(name),[]) if role is None or d['role_category']==role}.values())
        if owner:
            local=[d for d in rows if d['owner']==owner]
            if local:rows=local
        if selectors is not None:
            rows=[d for d in rows if all(public_name(selectors.get(k,''))==public_name(v) for k,v in d['identity_selectors'].items())]
        signatures={(d['role_category'],tuple(sorted((k,public_name(v)) for k,v in d['identity_selectors'].items())),
                     tuple(d['input_signature']),tuple(d['output_signature'])) for d in rows}
        if len(signatures)>1:return [],'ambiguous public role/signature'
        return rows,None
    public_groups=defaultdict(list)
    for d in definitions:
        sig=(public_name(d['name']),d['role_category'],tuple(sorted(d['identity_selectors'].items())),
             tuple(d['input_signature']),tuple(d['output_signature']))
        public_groups[sig].append(d)
    for group in public_groups.values():
        # A chain connects equivalent definitions without a quadratic clique.
        for left,right in zip(sorted(group,key=lambda d:d['id']),sorted(group,key=lambda d:d['id'])[1:]):
            edge(left['id'],right['id'],'SAME_PUBLIC_IDENTITY',support={'policy':'same source-verified name, role, signatures and selectors'})
    for f in facts:
        if f['owner_model']:
            ds,reason=candidates(f['owner_model'],owner=f['owner'])
            if reason:diagnostics.append({'node':f['id'],'reason':reason,'name':f['owner_model']})
            for d in ds:edge(d['id'],f['id'],'DESCRIBES',support={'policy':'explicit verified owner_model','evidence':f['evidence']})
    selectors=[];selector_definitions={};by_path=defaultdict(list)
    for n in list(nodes.values()):
        if n['kind']!='configuration' or n.get('literal_kind')!='entry' or n.get('flags'):continue
        name=literal_identifier(n.get('value',''));role=selector_role(n)
        if name and role:
            n['selector_role']=role;selectors.append(n);by_path[n['path']].append(n)
    for n in selectors:
        # thermoType selector entries share a physical dictionary prefix;
        # repeated dictionaries retain occurrence numbers and never mix.
        companions={s['key']:s['value'] for s in by_path[n['path']] if physical_prefix(s)==physical_prefix(n)}
        ds,reason=candidates(n['value'],n['selector_role'],companions)
        selector_definitions[n['id']]=ds
        if reason:diagnostics.append({'node':n['id'],'reason':reason,'name':n['value']})
        if not ds:diagnostics.append({'node':n['id'],'reason':'no unique source-verified public identity','name':n['value'],'role':n['selector_role']})
        for d in ds:edge(n['id'],d['id'],'DOCUMENTED_BY',support={'selector':n['evidence'],'definition':d['evidence'],
          'policy':'exact public identifier and typed role; required companion selectors explicitly checked'})
    # Parameter-to-model links require a typed physical namespace. Sharing a
    # parameter spelling such as pRef is insufficient to create any link.
    for n in list(nodes.values()):
        if n['kind']!='configuration' or n.get('flags') or n['id'] in selector_definitions:continue
        parts=n.get('components',[]);parents=parts[:-1];role=None;model_name=None
        if parents:
            role=PARAMETER_ROLES.get(parents[-1])
            if parents[-1].endswith('Coeffs'):model_name=parents[-1][:-6]
            if parents[0]=='functions':role='function_object'
            if 'boundaryField' in parents:role='boundary_condition'
        if role is None and model_name is None:continue
        options=[]
        for s in by_path[n['path']]:
            if role and s['selector_role']!=role:continue
            if model_name and public_name(s['value'])!=public_name(model_name):continue
            prefix=physical_prefix(s)
            if prefix and prefix[-1][0]=='thermoType':prefix=prefix[:-1]
            target_prefix=physical_prefix(n)
            if target_prefix[:len(prefix)]==prefix:options.append((len(prefix),s))
        if not options:continue
        depth=max(d for d,s in options);nearest=[s for d,s in options if d==depth]
        if len({(s['selector_role'],public_name(s['value'])) for s in nearest})!=1:
            diagnostics.append({'node':n['id'],'reason':'ambiguous nearest typed selector'});continue
        for s in nearest:edge(n['id'],s['id'],'PARAMETER_CONTEXT',support={'policy':'typed parameter namespace and nearest physical selector; values not executed'})
    for e in edges:
        e['cross_owner']=nodes[e['source']]['owner']!=nodes[e['target']]['owner']
        e['cross_file']=nodes[e['source']]['path']!=nodes[e['target']]['path']
    graph.update(schema='independent_verified_knowledge_graph_v1',source_hashes=source_hashes,
      semantic_processing_complete=complete,construction_binding=binding,
      quarantined_navigation_semantics=quarantined,
      link_diagnostics=diagnostics,link_policy='source-owned nodes; exact public identity plus typed role/signatures/selectors; physical namespace for parameters; no cooccurrence dependencies',
      condition_policy='separate source-verified applicability fields; not evaluated; original full text retained in every variant')
    graph['limits']+=['Independent source review is model-based, not human confirmation.',
      'Missing or ambiguous identities remain unlinked; all original source access stays available.',
      'No-cross-owner removes every owner-boundary edge, including nesting and same-file semantic links. Flat seeds may independently match multiple owners.',
      'No-condition removes structured condition use only; raw original condition clauses remain available.']
    return graph

def load_verified(output,source,allow_partial=False,allow_terminal_failures=False):
    plans=read(output/'semantic-units.json');protocol=read(output/'protocol.json');records=[];missing=[];bindings={};failures=[]
    for uid,unit in plans.items():
        if source['units'].get(uid)!=unit:raise ValueError('semantic plan differs from raw source partition')
        folder=output/'sessions'/identity('session',uid).split(':')[-1];p=folder/'accepted.json'
        if not p.exists():
            stages=[]
            for stage in ('extract','verify'):
                response=folder/'responses'/(stage+'.json')
                if response.exists():
                    r=read(response)
                    if sha(wire(r['request']).encode('utf-8'))!=r['request_sha256']:raise ValueError('failed request fingerprint drift')
                    stages.append({'stage':stage,'status':r['status'],'response_sha256':sha(response.read_bytes()),
                                   'reason':r.get('error'),'attempts':len(r['events'])})
            terminal=stages and stages[-1]['status'] in {'invalid_response','http_rejected','transport_error'}
            if terminal and allow_terminal_failures:
                failures.append({'unit_id':uid,'path':unit['path'],'start':unit['start'],'end':unit['end'],
                  'stages':stages,'semantic_items_retained':0,'original_source_available':True})
            else:missing.append(uid)
            continue
        record=read(p)
        for field in ('owner','path','sha256','start','end'):
            if record[field]!=unit[field]:raise ValueError('semantic source ownership drift')
        extraction=read(folder/'responses/extract.json');verification=read(folder/'responses/verify.json')
        if sha((folder/'responses/extract.json').read_bytes())!=record['extract_response_sha256'] or sha((folder/'responses/verify.json').read_bytes())!=record['verify_response_sha256']:
            raise ValueError('semantic response binding drift')
        for r in (extraction,verification):
            if sha(wire(r['request']).encode('utf-8'))!=r['request_sha256'] or r['status']!='response':raise ValueError('verified request fingerprint/status drift')
            if json.loads(r['raw_response_text'])!=r['response'] or r['response']['model']!=MODEL or r['response']['choices'][0]['finish_reason']!='stop':
                raise ValueError('verified provider response identity drift')
        # Recompute validation from preserved model responses, not trusted
        # editable accepted.json summaries.
        candidate=curate_extraction(json.loads(extraction['response']['choices'][0]['message']['content']),extraction['request'])
        if candidate!=extraction['parsed']:raise ValueError('source curation recomputation mismatch')
        numbered=[{'number':unit['start']+i,'text':line} for i,line in enumerate(unit['text'].splitlines())]
        if json.loads(extraction['request']['messages'][1]['content'])!={'source_unit':{**unit,'numbered_lines':numbered}}:
            raise ValueError('extractor source-only input drift')
        if extraction['request']['messages'][0]['content']!=protocol['extract_prompt'] or verification['request']['messages'][0]['content']!=protocol['verify_prompt']:
            raise ValueError('frozen source verification prompt drift')
        if json.loads(verification['request']['messages'][1]['content'])!={'source_unit':unit,'candidate':candidate}:
            raise ValueError('independent verifier did not receive actual unit and curated claims')
        verdict=validate_verification(json.loads(verification['response']['choices'][0]['message']['content']),verification['request'])
        if accepted_semantics(candidate,verdict)!=record['accepted']:raise ValueError('independent acceptance recomputation mismatch')
        records.append(record);bindings[uid]=sha(p.read_bytes())
    if missing and not allow_partial:raise ValueError('semantic processing incomplete; development-only partial graph requires explicit flag')
    return records,missing,bindings,failures

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--construction',type=Path,required=True)
    p.add_argument('--corpus',type=Path,required=True);p.add_argument('--manifest',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--allow-partial-development',action='store_true')
    p.add_argument('--allow-terminal-failures',action='store_true',help='Keep each terminal failed source unit visible with zero semantic items; never repeat content requests.')
    a=p.parse_args();root=a.construction.resolve()
    from chapter2_knowledge_input_guard import install
    install()
    protocol=read(root/'protocol.json');source=read(root/'source-graph.json')
    if sha((root/'source-graph.json').read_bytes())!=protocol['source_graph_sha256'] or sha((root/'semantic-units.json').read_bytes())!=protocol['semantic_units_sha256']:
        raise ValueError('construction source fingerprint drift')
    corpus=FrozenKnowledgeCorpus(a.corpus,a.manifest)
    if corpus.manifest_sha256!=source['corpus_manifest_sha256']:raise ValueError('independent source manifest differs')
    for unit in source['units'].values():
        if unit['text']!='\n'.join(corpus.lines(unit['path'])[unit['start']-1:unit['end']]):raise ValueError('original unit drift')
    records,missing,bindings,failures=load_verified(root,source,a.allow_partial_development,a.allow_terminal_failures)
    graph=compile_graph(source,records,corpus.hashes,complete=not missing,binding={
      'protocol_sha256':sha((root/'protocol.json').read_bytes()),'accepted_units':bindings,'missing_unit_ids':missing,
      'terminal_failed_units':failures,'semantic_verified_units':len(records),'semantic_planned_units':len(source['semantic_plans']) if 'semantic_plans' in source else len(read(root/'semantic-units.json')),
      'compiler_sha256':sha(Path(__file__).read_bytes())})
    if a.output.exists():raise FileExistsError('compiled graph is immutable; use a new version')
    save(a.output,graph)
    print(json.dumps({'nodes':len(graph['nodes']),'edges':len(graph['edges']),
      'relations':dict(Counter(e['relation'] for e in graph['edges'])),'complete':not missing,
      'terminal_failed_units':len(failures),'unresolved_links':len(graph['link_diagnostics']),'sha256':sha(a.output.read_bytes())}))

if __name__=='__main__':main()
