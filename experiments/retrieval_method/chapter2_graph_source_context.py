"""Persist literal fragment adjacency and source-derived case aliases only."""
from collections import defaultdict
from copy import deepcopy
import argparse
import json
from pathlib import Path,PurePosixPath
import re

from chapter2_graph_sources import identity
from chapter2_knowledge_graph_retriever import KnowledgeGraphRetriever,case_directory
from chapter2_v2_retrieval_probe import save,sha


def case_aliases(path):
    leaf=PurePosixPath(path).name
    parts=re.findall(r'[A-Z]+(?=[A-Z][a-z]|$)|[A-Z]?[a-z]+|[0-9]+',leaf)
    significant=[p for p in parts if p.casefold() not in {'to','with','and','of','the','a','an','in','for'}]
    acronym=''.join(p[0].upper() for p in significant)
    return sorted({leaf,*([acronym] if 3<=len(acronym)<=8 else [])})


def source_case(path):
    parts=PurePosixPath(path).parts
    if parts and parts[0]=='tutorials':
        for i,part in enumerate(parts):
            if part in {'system','constant','0','0.orig','0.org'} and i>=2:return '/'.join(parts[:i])
    return case_directory(path)


def add_source_context(original):
    graph=deepcopy(original);by_path=defaultdict(list)
    raw={n['unit_id']:n for n in graph['nodes'].values() if n['kind']=='original_unit'}
    for unit in graph['units'].values():
        case=source_case(unit['path'])
        unit['source_context']=dict(filename=PurePosixPath(unit['path']).name,
            case_directory=case,case_aliases=case_aliases(case) if case else [],
            identity_policy='Literal source path and mechanically derived significant-word initialism; no semantic equivalence or execution claim.')
        by_path[unit['path']].append(unit)
    existing={e['id'] for e in graph['edges']};added=0
    containers={};parent_edges=0
    for path,units in sorted(by_path.items()):
        units.sort(key=lambda u:u['start'])
        scopes={}
        if units[0]['kind']=='markdown_section':
            for unit in units:
                for heading in unit.get('context',[]):
                    key=('markdown_parent',heading['line'])
                    scopes.setdefault(key,[]).append(unit)
        elif units[0]['kind']=='dictionary_scope':
            header_end=max((u['end'] for u in units if re.search(r'"key"\s*:\s*"FoamFile"',u['owner_key'])),default=0)
            for unit in units:
                if unit['start']<=header_end:continue
                components=json.loads(unit['owner_key'].split(':',1)[1])
                for length in range(len(components)+1):
                    key=('dictionary_parent',json.dumps(components[:length],sort_keys=True))
                    scopes.setdefault(key,[]).append(unit)
        else:scopes[('original_file',0)]=units
        for (kind,key),members in scopes.items():
            # A real source parent has contiguous original membership. No text
            # from another file or guessed executable scope is attached.
            members=sorted({u['id']:u for u in members}.values(),key=lambda u:u['start'])
            if any(l['end']+1!=r['start'] for l,r in zip(members,members[1:])):continue
            cid=identity('source_container',path,members[0]['sha256'],kind,key)
            containers[cid]=dict(id=cid,kind=kind,path=path,sha256=members[0]['sha256'],
                start=members[0]['start'],end=members[-1]['end'],members=[u['id'] for u in members],
                characters=sum(len(u['text'])+1 for u in members)-1,
                status='physical_original_parent_not_effective_runtime_scope')
            parent=raw[members[0]['id']]
            for unit in members:
                unit.setdefault('parent_context_ids',[]).append(cid)
                child=raw[unit['id']]
                if child['id']==parent['id']:continue
                eid=identity('edge',child['id'],parent['id'],'SOURCE_PARENT_CONTEXT',cid)
                if eid in existing:continue
                graph['edges'].append(dict(id=eid,source=child['id'],target=parent['id'],relation='SOURCE_PARENT_CONTEXT',
                    cross_owner=child['owner']!=parent['owner'],cross_file=False,conditions=[],
                    status='literal_parent_membership_not_semantic_entailment',support=dict(container_id=cid,path=path,sha256=unit['sha256'])))
                existing.add(eid);parent_edges+=1
        for left,right in zip(units,units[1:]):
            if left['end']+1!=right['start']:raise ValueError('Source partition adjacency is not contiguous')
            a,b=raw[left['id']],raw[right['id']]
            eid=identity('edge',a['id'],b['id'],'SOURCE_NEXT_FRAGMENT')
            if eid in existing:continue
            graph['edges'].append(dict(id=eid,source=a['id'],target=b['id'],relation='SOURCE_NEXT_FRAGMENT',
                cross_owner=a['owner']!=b['owner'],cross_file=False,conditions=[],
                status='literal_contiguous_original_fragments_not_semantic_entailment',
                support=dict(path=path,sha256=left['sha256'],left_end=left['end'],right_start=right['start'])))
            existing.add(eid);added+=1
    graph['source_containers']=containers
    # Forward, literal file declarations, not a term-to-document index. These
    # let a parent file corroborate keys split across its physical children.
    declarations={}
    for path,units in by_path.items():
        keys=set()
        for unit in units:
            if unit['kind']!='dictionary_scope':continue
            components=json.loads(unit['owner_key'].split(':',1)[1])
            if any(c['key']=='FoamFile' for c in components):continue
            keys.update(c['key'] for c in components)
        if keys:declarations[path]=dict(keys=sorted(keys),sha256=units[0]['sha256'],
            status='literal_physical_declarations_not_effective_runtime_values')
    graph['source_file_declarations']=declarations
    graph['source_context_revision']=dict(schema='literal_source_context_graph_v1',
        added_adjacency_edges=added,added_parent_edges=parent_edges,original_parent_containers=len(containers),questions_or_gold_used=False,model_calls=0,
        limits='Aliases are literal identity hints. Adjacent text retains its original owner and does not assert compatibility, activation or causal dependence.')
    return graph


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('graph','corpus','source-map','output'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args()
    from chapter2_knowledge_input_guard import install
    install()
    engine=KnowledgeGraphRetriever(a.graph,a.corpus,corpus_manifest=a.source_map)
    for unit in engine.graph['units'].values():
        if unit['text']!='\n'.join(engine.source_lines(unit['path'])[unit['start']-1:unit['end']]):raise ValueError('Original unit text drift')
    graph=add_source_context(engine.graph)
    graph['source_context_revision'].update(input_graph_sha256=engine.graph_sha256,builder_sha256=sha(Path(__file__)))
    save(a.output,graph)
    print(graph['source_context_revision'],flush=True)


if __name__=='__main__':main()
