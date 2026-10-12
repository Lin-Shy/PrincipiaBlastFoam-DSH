from test_evidence_bundle import engine,SKILL
import evidence_bundle as b
import edit_graph as e
import pytest


def test_dictionary_scope_retains_actual_entries_and_original_task(engine):
    search=e.EditSearch(engine)
    p=search.locate('sampling fields in sensor','caseA',query='mesh',budget=5000)
    assert any(x['dictionary']=='functions/sensor' for x in p['locations'])
    for x in p['locations']:
        assert search.raw(search.nodes[x['id']]).startswith(x['text'])
        if x['complete']:assert search.raw(search.nodes[x['id']])==x['text']
    assert len(b.wire(p))<=5000
    with pytest.raises(ValueError):search.locate('sampling','missing')
    with pytest.raises(ValueError):search.locate('','caseA')


def test_selector_coefficients_stay_in_phase_and_budget(engine):
    p=engine.skill/'corpus/tutorials/caseA/constant/phaseProperties';p.parent.mkdir()
    p.write_text('air\n{\n thermoType\n {\n transport const;\n }\n transport\n {\n mu 0;\n Pr 1;\n }\n}\nfuel\n{\n thermoType\n {\n transport const;\n }\n transport\n {\n mu 2;\n Pr 1;\n }\n}\n')
    b.k.build(SKILL,engine.skill/'corpus',engine.skill/'index')
    search=e.EditSearch(b.EvidenceSearch(b.build(engine.skill),engine.skill))
    links=[x for x in search.graph['edges'] if x['relation']=='SELECTOR_COEFFICIENTS']
    assert len(links)==2
    for link in links:
        a,z=(search.nodes[link[k]] for k in ['source','target'])
        assert a['scope'].split('/')[0]==z['scope'].split('/')[0]
    packet=search.locate('air transport viscosity','caseA',budget=3000)
    assert packet['locations'][0]['dictionary'].startswith('air/')
    for use_graph in (False,True):
        shared_key=search.locate('air transport Pr viscosity','caseA',budget=3000,graph=use_graph)
        assert shared_key['locations'][0]['dictionary'].startswith('air/')
    ids={n['id'] for n in packet['locations']}
    assert all(x['source'] in ids and x['target'] in ids for x in packet['relations'])
    plain=search.locate('air transport','caseA',budget=1000,graph=False)
    assert not plain['relations'] and len(b.wire(plain))<=1000


def test_family_option_requires_named_candidate_and_keeps_source(engine):
    search=e.EditSearch(engine)
    links=[x for x in search.graph['edges'] if x['relation']=='MODEL_FAMILY_OPTION']
    assert links
    assert all(x['status']=='same_manual_family_not_compatibility' for x in links)
    packet=search.locate('sensor otherModel','caseA',budget=6000)
    options=[x for x in packet['locations'] if x['reason']=='linked_scope' and 'otherModel' in x['dictionary']]
    assert options and 'Unrelated definition' in options[0]['text']
    packet=search.locate('sensor sampling fields','caseA',budget=6000)
    assert not any('otherModel' in x['dictionary'] for x in packet['locations'])


def test_aggregating_scope_preserves_which_selector_owns_each_definition(engine,monkeypatch):
    path='tutorials/caseA/constant/phaseProperties';manual='manual/markdown/01_sampling.md'
    nodes=[]
    for uid,key,value in [('t','gas/thermoType/transport','const'),('e','gas/thermoType/equationOfState','idealGas'),
                          ('mu','gas/transport/mu','0'),('gamma','gas/equationOfState/gamma','1.4')]:
        nodes.append({'id':uid,'kind':'configuration','dictionary_path':key,'value':value,
                      'line_start':1,'line_end':1,'evidence':{'path':path}})
    edges=[]
    for uid,label,line,selector in [('dt','const',5,'t'),('de','idealGas',9,'e')]:
        ev={'path':manual,'line_start':line,'line_end':line}
        nodes.append({'id':uid,'kind':'manual_section','title':label,'hierarchy':[label],'evidence':ev})
        edges.extend([{'source':selector,'target':uid,'relation':'REFERS_TO_DEFINITION','status':'source_match'},
                      {'source':uid,'target':'page','relation':'DOCUMENTED_ON','evidence':ev}])
    original=b.k.read_json
    monkeypatch.setattr(b.k,'read_json',lambda p: {'nodes':nodes,'edges':edges} if str(p).endswith('/graph.json') else original(p))
    graph=e.build(engine);byid={n['id']:n for n in graph['nodes']}
    bindings={(byid[x['source']]['scope'],byid[x['target']]['scope']) for x in graph['edges'] if x['relation']=='DOCUMENTED_COEFFICIENTS'}
    assert bindings=={('gas/transport','const'),('gas/equationOfState','idealGas')}


def test_large_relevant_scope_is_not_lost_only_because_full_text_exceeds_budget(engine):
    path=engine.skill/'corpus/tutorials/caseA/system/controlDict'
    path.write_text('endTime 3;\n'+''.join(f'other{i} "'+('long value '*30)+'";\n' for i in range(8)))
    b.k.build(SKILL,engine.skill/'corpus',engine.skill/'index')
    search=e.EditSearch(b.EvidenceSearch(b.build(engine.skill),engine.skill))
    packet=search.locate('change endTime','caseA',budget=1000,graph=False)
    location=packet['locations'][0]
    assert location['path'].endswith('system/controlDict') and not location['complete']
    assert path.read_text().startswith(location['text']) and len(b.wire(packet))<=1000


def test_second_location_covers_another_explicit_key(engine):
    path=engine.skill/'corpus/tutorials/caseA/constant/phaseProperties';path.parent.mkdir()
    path.write_text('gas { transport {Pr 1; mu 0;} equationOfState {gamma 1.4;} }')
    control=engine.skill/'corpus/tutorials/caseA/system/controlDict'
    control.write_text('endTime 1; deltaT 0.01; maxDeltaT 0.1;')
    b.k.build(SKILL,engine.skill/'corpus',engine.skill/'index')
    search=e.EditSearch(b.EvidenceSearch(b.build(engine.skill),engine.skill))
    for graph in (False,True):
        packet=search.locate('gas transport Pr viscosity endTime deltaT maxDeltaT','caseA',budget=5000,graph=graph)
        assert any(x['path'].endswith('/system/controlDict') for x in packet['locations'][:2])


def test_prose_compound_object_name_preserves_function_scope(engine):
    path=engine.skill/'corpus/tutorials/caseA/system/controlDict'
    path.write_text(path.read_text().replace('sensor','thermalSensors'))
    b.k.build(SKILL,engine.skill/'corpus',engine.skill/'index')
    search=e.EditSearch(b.EvidenceSearch(b.build(engine.skill),engine.skill))
    for graph in (False,True):
        packet=search.locate('change thermal sensors sampling interval, preserve field output','caseA',budget=5000,graph=graph)
        assert packet['locations'][0]['dictionary']=='functions/thermalSensors'
        assert 'functions/thermalSensors/writeInterval' in packet['locations'][0]['entries']
        singular=search.locate('thermal sensor output; preserve top-level writeControl/writeInterval','caseA',budget=5000,graph=graph)
        assert singular['locations'][0]['dictionary']=='functions/thermalSensors'


def test_shared_compound_dictionary_name_does_not_override_named_phase(engine):
    path=engine.skill/'corpus/tutorials/caseA/constant/phaseProperties';path.parent.mkdir()
    path.write_text('gas\n{\n transport\n {\n Pr 1;\n mu 0;\n }\n equationOfState\n {\n gamma 1.4;\n }\n}\nfuel\n{\n equationOfState\n {\n gamma 1.2; // equation of state\n }\n}\n')
    b.k.build(SKILL,engine.skill/'corpus',engine.skill/'index')
    search=e.EditSearch(b.EvidenceSearch(b.build(engine.skill),engine.skill))
    packet=search.locate('gas transport Pr, preserve equation of state','caseA',budget=5000)
    assert all(x['dictionary'].startswith('gas/') for x in packet['locations'][:2])


def test_linked_source_reserves_relation_before_truncating(engine,monkeypatch):
    search=e.EditSearch(engine)
    options=[x for x in search.graph['edges'] if x['relation']=='MODEL_FAMILY_OPTION']
    assert options and all(x.get('selector_entry') for x in options)
    raw=search.raw
    monkeypatch.setattr(search,'raw',lambda n: raw(n)+(' source detail'*2000 if 'otherModel' in n['scope'] else ''))
    packet=search.locate('sensor otherModel','caseA',budget=1800)
    linked=[x for x in packet['locations'] if 'otherModel' in x['dictionary']]
    assert linked and not linked[0]['complete'] and linked[0]['text']
    assert any(x['target']==linked[0]['id'] for x in packet['relations'])
    assert len(b.wire(packet))<=1800
