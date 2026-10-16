"""Add exact original heading hierarchy to an independently verified graph.

This deterministic structural pass makes no semantic claims or model calls.
Semantic extraction/verification continues to use exact deepseek-flash.
"""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from chapter2_graph_sources import identity
from chapter2_knowledge_graph_retriever import KnowledgeGraphRetriever


def add_source_hierarchy(original):
    graph = deepcopy(original)
    units, nodes = graph['units'], graph['nodes']
    raw_nodes = {n['unit_id']: n for n in nodes.values() if n['kind'] == 'original_unit'}
    headings = {}
    for unit in units.values():
        context = unit.get('context', [])
        if context and context[-1]['line'] == unit['start']:
            headings[(unit['path'], unit['start'])] = unit
    existing = {e['id'] for e in graph['edges']}
    added = 0
    for unit in units.values():
        context = unit.get('context', [])
        # For a split long section, link its fragment to that section's first
        # original unit; otherwise link a heading to its nearest real ancestor.
        ancestors = [c for c in context if c['line'] < unit['start']]
        if not ancestors:
            continue
        parent = headings.get((unit['path'], ancestors[-1]['line']))
        if parent is None or parent['id'] == unit['id']:
            continue
        left, right = raw_nodes[unit['id']], raw_nodes[parent['id']]
        eid = identity('edge', left['id'], right['id'], 'SOURCE_SECTION_PARENT')
        if eid in existing:
            continue
        existing.add(eid)
        graph['edges'].append(dict(id=eid, source=left['id'], target=right['id'],
            relation='SOURCE_SECTION_PARENT', conditions=[],
            cross_owner=left['owner'] != right['owner'], cross_file=False,
            status='literal_original_heading_hierarchy_not_semantic_entailment',
            support=dict(path=unit['path'], sha256=unit['sha256'],
                child_start=unit['start'], parent_heading_line=parent['start'])))
        added += 1
    graph['development_revision'] = dict(
        schema='source_hierarchy_candidate_v2', added_heading_edges=added,
        questions_or_gold_used=False, semantic_model_calls=0,
        policy='Original heading hierarchy only; no inferred causal or dependency relation.')
    return graph


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('graph', 'corpus', 'source-map', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    from chapter2_knowledge_input_guard import install
    install()
    engine = KnowledgeGraphRetriever(args.graph, args.corpus, corpus_manifest=args.source_map)
    for unit in engine.graph['units'].values():
        if unit['text'] != '\n'.join(engine.source_lines(unit['path'])[unit['start']-1:unit['end']]):
            raise ValueError('Original graph unit text drift')
    result = add_source_hierarchy(engine.graph)
    result['development_revision'].update(input_graph_sha256=engine.graph_sha256,
        builder_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(json.dumps(result['development_revision']), flush=True)


if __name__ == '__main__':
    main()
