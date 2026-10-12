from test_evidence_bundle import engine
from test_condition_graph import index
from condition_graph import ConditionalEditSearch
from navigation_packet import build
import evidence_bundle as b


def test_packet_preserves_actual_values_and_verifiable_sources(engine):
    nav=ConditionalEditSearch(engine,index(engine))
    packet=build(nav,'sampling fields sensor','caseA',budget=5000)
    assert packet['conditions'][0]['evaluation']=='not_evaluated'
    for location in packet['locations']:
        parsed,_=b.k.parse_dictionary((engine.skill/'corpus'/location['path']).read_text())
        actual={e['dictionary_path']:e['value'] for e in parsed}
        assert all(actual[k]==v for k,v in location['values'].items())
    sources={s['id']:s for s in packet['sources']}
    assert all(ref in sources for c in packet['conditions'] for ref in c['support'])
    for source in sources.values():
        if source['quote'] is None:continue
        lines=(engine.skill/'corpus'/source['path']).read_text().splitlines(keepends=True)
        assert source['quote'] in ''.join(lines[source['start']-1:source['end']])


def test_small_budget_reports_omissions_without_dangling_references(engine):
    nav=ConditionalEditSearch(engine,index(engine))
    for budget in (1000,1500,2400):
        packet=build(nav,'sampling fields sensor','caseA',budget=budget)
        assert len(b.wire(packet))<=budget
        if packet['status']=='insufficient_budget':continue
        sources={s['id'] for s in packet['sources']}
        assert all(ref in sources for c in packet['conditions'] for ref in c['support'])
        if packet['omitted'] or any(s['quote'] is None for s in packet['sources']):
            assert packet['status']=='partial'
