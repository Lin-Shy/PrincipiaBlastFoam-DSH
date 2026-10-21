"""Literal source heading nodes and directed documentation references, no LLM."""
import argparse
from collections import defaultdict
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

from chapter2_graph_sources import identity

def augment(original):
    graph=deepcopy(original); targets=defaultdict(list);added=0
    generic={'none','constant','const','linear','type','basic','solid','fluid','true','false','yes','no'}
    for unit in graph['units'].values():
        if not unit['path'].startswith('manual/'):continue
        context=unit.get('context',[])
        if not context:continue
        heading=context[-1]
        name=re.sub(r'^\d+(?:\.\d+)*\.?\s*','',heading['title']).strip().strip('`')
        if not (re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*',name) and len(name)>=3):continue
        if name.casefold() in generic or not unit['start']<=heading['line']<=unit['end']:continue
        nid=identity('literal_heading',unit['id'],name)
        if nid not in graph['nodes']:
            graph['nodes'][nid]=dict(id=nid,kind='literal_heading',unit_id=unit['id'],owner=unit['owner'],
                path=unit['path'],name=name,label=name,aliases=[],conditions=[],body='',
                evidence=[dict(path=unit['path'],sha256=unit['sha256'],start=heading['line'],end=heading['line'],
                    quote=unit['text'].splitlines()[heading['line']-unit['start']])],
                status='literal_original_heading_not_semantic_model_identity')
            added+=1
        targets[name.casefold()].append(nid)
    linked=0;ambiguous=[];existing={e['id'] for e in graph['edges']}
    for node in list(graph['nodes'].values()):
        if node['kind']!='configuration':continue
        value=str(node.get('value') or '').strip().strip('"')
        matches=targets.get(value.casefold(),[])
        if len(matches)>1:
            ambiguous.append(dict(node_id=node['id'],literal=value,target_count=len(matches)));continue
        if len(matches)!=1:continue
        target=graph['nodes'][matches[0]]
        eid=identity('edge',node['id'],target['id'],'LITERAL_HEADING_REFERENCE')
        if eid in existing:continue
        graph['edges'].append(dict(id=eid,source=node['id'],target=target['id'],
            relation='LITERAL_HEADING_REFERENCE',cross_owner=node['owner']!=target['owner'],
            cross_file=node['path']!=target['path'],conditions=[],
            status='directed_literal_documentation_lookup_not_equivalence_or_execution',
            support=dict(selector_key=node.get('key'),literal=value,source_evidence=node['evidence'],target_evidence=target['evidence'])))
        existing.add(eid);linked+=1
    graph['literal_heading_revision']=dict(schema='literal_heading_documentation_v1',
        heading_nodes_added=added,directed_literal_references_added=linked,ambiguous_references_not_linked=ambiguous,
        questions_or_gold_used=False,model_calls=0,
        boundary='Literal heading lookup supplies candidate documentation, not a semantic identity, dependency or verified compatibility claim.')
    return graph

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--graph',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    from chapter2_knowledge_input_guard import install
    install()
    raw=a.graph.read_bytes();g=augment(json.loads(raw))
    g['literal_heading_revision'].update(input_graph_sha256=hashlib.sha256(raw).hexdigest(),
        builder_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open('x',encoding='utf-8') as f:json.dump(g,f,ensure_ascii=False,indent=2)
    print(json.dumps({k:v for k,v in g['literal_heading_revision'].items() if k!='ambiguous_references_not_linked'}))
if __name__=='__main__':main()
