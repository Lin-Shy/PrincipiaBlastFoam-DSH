from test_evidence_bundle import engine,SKILL
from test_model_input_schema import C,H
import evidence_bundle as b
import edit_graph as e


def test_two_literal_input_keys_reach_schema_without_model_name(engine):
    folder=engine.skill/'corpus/manual/source_code/demo';folder.mkdir(parents=True)
    (folder/'Demo.C').write_text(C.replace('"A"','"CoefA"').replace('"B"','"CoefB"'))
    (folder/'Demo.H').write_text(H)
    b.k.build(SKILL,engine.skill/'corpus',engine.skill/'index')
    search=e.EditSearch(b.EvidenceSearch(b.build(engine.skill),engine.skill))
    packet=search.locate('sensor CoefA=2 CoefB=3','caseA')
    assert any(x['dictionary']=='otherModel/coeffs' for x in packet['locations'])
    for graph,query in [(False,'sensor CoefA=2 CoefB=3'),(True,'sensor CoefA=2')]:
        assert not any(x['dictionary']=='otherModel/coeffs' for x in search.locate(query,'caseA',graph=graph)['locations'])


def test_candidate_request_retains_multiple_options_and_selector_pair(engine):
    manual=engine.skill/'corpus/manual/markdown/01_sampling.md'
    manual.write_text(manual.read_text().replace('Unrelated definition in the same chapter.','Temperature viscosity relation.')+'\n## 1.3 thirdModel\n\nTemperature viscosity polynomial.\n')
    path=engine.skill/'corpus/tutorials/caseA/constant/phaseProperties';path.parent.mkdir()
    path.write_text('gas { thermoType { transport sampling; } transport { mu 0; } }\n')
    b.k.build(SKILL,engine.skill/'corpus',engine.skill/'index')
    search=e.EditSearch(b.EvidenceSearch(b.build(engine.skill),engine.skill))
    # Synthetic selector binding isolates candidate traversal from the manual
    # parser's domain-specific classification of transport section titles.
    graph=search.graph
    selector=next(n['id'] for n in graph['nodes'] if n['scope']=='gas/thermoType')
    for n in graph['nodes']:
        if n['kind']=='manual' and any(name in n['scope'] for name in ('otherModel','thirdModel')):
            graph['edges'].append({'source':selector,'target':n['id'],'relation':'MODEL_FAMILY_OPTION',
                                  'selector_entry':'gas/thermoType/transport','status':'fixture'})
    graph['snapshot']=b.sha({k:v for k,v in graph.items() if k!='snapshot'})
    search=e.EditSearch(search.engine,graph)
    p=search.locate('gas transport temperature viscosity candidate models','caseA',budget=5000)
    assert {x['model'] for x in p['model_candidates']['options']}=={'otherModel','thirdModel'}
    assert p['model_candidates']['selector_entry']=='gas/thermoType/transport'
    assert {x['dictionary'] for x in p['locations'][:2]}=={'gas/transport','gas/thermoType'}
    assert 'model_candidates' not in search.locate('gas transport temperature viscosity','caseA')
    assert 'model_candidates' not in search.locate('gas transport temperature viscosity candidates','caseA',graph=False)
    assert len(b.wire(search.locate('gas transport temperature viscosity candidates','caseA',budget=1000)))<=1000
