"""Source-only construction of file-level selector context, never execution."""
from collections import defaultdict
from copy import deepcopy
import argparse
import json
from pathlib import Path
import re

from chapter2_graph_sources import identity
from chapter2_knowledge_graph_retriever import KnowledgeGraphRetriever
from chapter2_v2_retrieval_probe import save,sha


def add_file_selectors(original):
    graph=deepcopy(original);nodes=graph['nodes'];groups=defaultdict(list)
    for node in nodes.values():
        if (node['kind']=='configuration' and node.get('literal_kind')=='entry' and
            node.get('components') in (['type'],['application']) and not node.get('flags') and
            re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',node.get('value',''))):
            groups[(node['path'],node['key'])].append(node)
    by_path=defaultdict(list);ambiguous=[]
    for (path,key),selectors in groups.items():
        if len(selectors)!=1:
            ambiguous.append(dict(path=path,key=key,occurrences=len(selectors)))
        else:by_path[path].append(selectors[0])
    existing={e['id'] for e in graph['edges']};added=0
    for node in nodes.values():
        if node.get('dictionary','').startswith('FoamFile'):continue
        if node['kind'] not in {'configuration','dictionary','original_unit'}:continue
        for selector in by_path.get(node['path'],[]):
            if node['id']==selector['id']:continue
            eid=identity('edge',node['id'],selector['id'],'FILE_SELECTOR_CONTEXT')
            if eid in existing:continue
            existing.add(eid)
            graph['edges'].append(dict(id=eid,source=node['id'],target=selector['id'],
                relation='FILE_SELECTOR_CONTEXT',conditions=[],cross_file=False,
                cross_owner=node['owner']!=selector['owner'],
                status='literal_file_context_not_effective_runtime_selection',
                support=dict(selector_evidence=selector['evidence'],
                    policy='Unique top-level literal type/application in this exact original file. Command-line overrides and includes are not evaluated.')))
            added+=1
    graph['selector_context_revision']=dict(schema='literal_file_selector_context_v1',
        questions_or_gold_used=False,model_calls=0,added_edges=added,
        files_with_unique_literal_selectors=len(by_path),ambiguous_selectors_unlinked=ambiguous,
        limits='The edge requests original file context. It does not assert activation, compatibility, or effective runtime selection.')
    return graph


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('graph','corpus','source-map','output'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args()
    from chapter2_knowledge_input_guard import install
    install()
    engine=KnowledgeGraphRetriever(a.graph,a.corpus,corpus_manifest=a.source_map)
    graph=add_file_selectors(engine.graph)
    graph['selector_context_revision'].update(input_graph_sha256=engine.graph_sha256,builder_sha256=sha(Path(__file__)))
    save(a.output,graph)
    print(json.dumps(graph['selector_context_revision']),flush=True)


if __name__=='__main__':main()
