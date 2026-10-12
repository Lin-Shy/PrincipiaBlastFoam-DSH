"""Observable source-map invariants on the independent sampling fixture."""
from test_evidence_bundle import engine
import evidence_bundle as b
from locate import locate
import pytest


@pytest.mark.parametrize('budget', [1000, 1800, 3000, 6000])
def test_budget_provenance_and_closed_relations(engine, budget):
    packet, audit = locate(engine, 'sampling pressure output', budget)
    assert len(b.wire(packet)) <= budget
    ids = {x['id'] for x in packet['locations']}
    for x in packet['locations']:
        text = ''.join((engine.skill / 'corpus' / x['path']).read_text().splitlines(keepends=True)[x['start']-1:x['end']])
        assert text.startswith(x['preview'])
    assert all(e['from'] in ids and e['to'] in ids for e in packet['relations'])
    assert all(e in engine.graph['edges'] + engine._locator_domain['edges'] for e in audit['relations'])


def test_graph_adds_related_locations_without_known_ids(engine):
    graph, audit = locate(engine, 'sampling pressure output', 6000)
    text, _ = locate(engine, 'sampling pressure output', 6000, graph=False)
    assert graph['relations'] and not text['relations']
    assert {x['path'] for x in text['locations']} <= {x['path'] for x in graph['locations']}
    assert audit['relations']


def test_no_match_and_original_preserved(engine):
    packet, _ = locate(engine, 'zzznothing999')
    assert packet['status'] == 'no_match' and not packet['locations']
    _, audit = locate(engine, '记录采样', translation='sampling output')
    assert audit['original_query'] == '记录采样'
    assert audit['translation'] == 'sampling output'
    with pytest.raises(ValueError):
        locate(engine, 'sampling', True)
