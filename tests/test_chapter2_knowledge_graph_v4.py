import json
from pathlib import Path
import sys
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'experiments/retrieval_method'))
from test_chapter2_graph_source_context import fixture as original_fixture
from chapter2_knowledge_graph_v4 import AdaptiveSourceGraph, _ForwardGraphScan
from chapter2_knowledge_graph_v3 import SourceContextGraph
from chapter2_knowledge_graph_v2 import EvidenceGraphV2


def fixture(tmp_path, files, **options):
    graph, previous = original_fixture(tmp_path, files)
    return graph, AdaptiveSourceGraph(tmp_path / 'graph.json', previous.root, corpus_manifest=tmp_path / 'authority.json', **options)


def test_forward_cache_preserves_ascii_camel_case_matching_scores(tmp_path):
    _, engine = fixture(tmp_path, {'manual/models.md': '# Models\n## PressureSolver\nThe pressure field uses pressureSolver and maxLevel.\n'})
    for query in ['pressure field', 'pressureSolver maxLevel', 'PressureSolver 的定义']:
        reference = EvidenceGraphV2._facet_flat(engine, query)
        cached = _ForwardGraphScan._facet_flat(engine, query)
        assert [(r['node_id'], r['score']) for r in reference['items']] == [(r['node_id'], r['score']) for r in cached['items']]
    assert AdaptiveSourceGraph.__mro__.index(SourceContextGraph) < AdaptiveSourceGraph.__mro__.index(_ForwardGraphScan)


def test_no_extension_preserves_full_flat_seeds_and_scores(tmp_path):
    text = 'FoamFile\n{\n class dictionary;\n object modes;\n}\ntype hydrostatic;\nhydrostaticCoeffs\n{\n value 1;\n}\ntableCoeffs\n{\n value 2;\n}\n'
    _, full = fixture(tmp_path, {'tutorials/demo/system/modes': text})
    flat = AdaptiveSourceGraph(tmp_path / 'graph.json', full.root, corpus_manifest=tmp_path / 'authority.json', options={'with_paths': False})
    query = 'hydrostaticCoeffs tableCoeffs'
    expected = full._facet_flat(query)['diagnostic']['seeds']
    actual = flat._facet_flat(query)['diagnostic']['seeds']
    assert [(r['node_id'], r['score']) for r in actual] == [(r['node_id'], r['score']) for r in expected]
    packet = flat.read_native(flat.rank(query))
    assert all(not c['route'] for row in packet['items'] for c in row['context_fragments'])


def test_adaptive_parent_requires_strict_hit_fraction_and_delivers_anchor_first(tmp_path):
    _, engine = fixture(tmp_path, {'manual/models.md': '# Models\nintro\n## Pressure\npressure target\n## Impulse\nimpulse target\n'})
    ranking = engine.rank('pressure impulse')
    row = next(r for r in ranking['items'] if engine.graph['units'][engine.nodes[r['node_id']]['unit_id']]['start'] == 3)
    uid = engine.nodes[row['node_id']]['unit_id']
    _, _, decisions = engine._select_context(row, {uid})
    assert not any(d['eligible'] for d in decisions)
    hits = {v['id'] for v in engine.graph['units'].values() if v['start'] >= 3}
    selected, routes, decisions = engine._select_context(row, hits)
    assert any(d['eligible'] for d in decisions)
    assert any(step['relation'] == 'SOURCE_PARENT_CONTEXT' for route in routes.values() for step in route)
    packet = engine.read_native({**ranking, 'items': [row, *[r for r in ranking['items'] if r is not row]]})
    assert packet['items'][0]['ranges'][0]['start'] == 3
    assert len(selected) == 3


@pytest.mark.parametrize('options', [{'with_cross': False}, {'with_paths': False}])
def test_ablation_blocks_all_owner_crossings_in_context_and_routes(tmp_path, options):
    _, engine = fixture(tmp_path, {'manual/models.md': '# Models\nintro\n## Pressure\npressure\n## Impulse\nimpulse\n'}, options=options)
    packet = engine.read_native(engine.rank('pressure impulse'))
    assert all(c['owner'] == row['owner'] for row in packet['items'] for c in row['context_fragments'])
    assert all(not step['cross_owner'] for row in packet['items'] for c in row['context_fragments'] for step in c['route'])


def test_context_ablations_share_identical_native_ranking(tmp_path):
    _, full = fixture(tmp_path, {'manual/models.md': '# Models\nintro\n## Pressure\npressure\n## Impulse\nimpulse\n'})
    expected = [(r['node_id'], r['score']) for r in full.rank('pressure impulse')['items']]
    for policy in ['adjacent', 'none', 'blanket']:
        engine = AdaptiveSourceGraph(tmp_path / 'graph.json', full.root, corpus_manifest=tmp_path / 'authority.json', context_policy=policy)
        ranking = engine.rank('pressure impulse')
        assert [(r['node_id'], r['score']) for r in ranking['items']] == expected
        if policy == 'none':
            packet = engine.read_native(ranking)
            assert all(len(r['context_fragments']) == 1 for r in packet['items'])


def test_source_case_scope_also_applies_to_propagated_nodes(tmp_path):
    graph, engine = fixture(tmp_path, {
        'tutorials/solver/thermalToPressureTransition/0/Su': 'internalField uniform 0.2;',
        'tutorials/solver/otherCase/0/Su': 'internalField uniform 0.9;'})
    nodes = list(graph['nodes'].values()); a = next(n for n in nodes if 'thermalToPressure' in n['path']); b = next(n for n in nodes if '/otherCase/' in n['path'])
    graph['edges'].append(dict(id='scope-test', source=a['id'], target=b['id'], relation='SAME_PUBLIC_IDENTITY',
        cross_owner=True, conditions=[]))
    (tmp_path / 'graph.json').write_text(json.dumps(graph), encoding='utf-8')
    engine = AdaptiveSourceGraph(tmp_path / 'graph.json', engine.root, corpus_manifest=tmp_path / 'authority.json')
    result = engine.rank('TPT 0/Su internalField')
    assert result['items'] and all('/otherCase/' not in r['path'] for r in result['items'])


def test_manual_scope_and_unicode_definition_survive_cached_graph_scan(tmp_path):
    _, engine = fixture(tmp_path, {'manual/models.md': '# Models\n## Lohner\nerror definition\n',
        'tutorials/solver/demo/system/Lohner': 'Löhner example\n'})
    result = engine.rank('只依据手册说明 Löhner')
    assert result['items'] and all(r['path'].startswith('manual/') for r in result['items'])
    assert result['items'][0]['reasons']['direct_heading_identifiers'] == ['lohner']
