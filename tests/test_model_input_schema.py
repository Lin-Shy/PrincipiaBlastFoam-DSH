from test_evidence_bundle import engine,SKILL
import evidence_bundle as b
import edit_graph as e

C='''template<class Thermo>
Foam::scalar Foam::Demo<Thermo>::readCoeff
(const word& coeffName, const dictionary& dict)
{
    return dict.subDict("coeffs").lookup<scalar>(coeffName);
}
Foam::Demo<Thermo>::Demo(const dictionary& dict)
:
    Thermo(dict),
    A_(readCoeff("A", dict)),
    B_(readCoeff("B", dict))
{}
'''
H='''class Demo { static word typeName() { return "otherModel<" + Thermo::typeName() + '>'; } };'''


def test_direct_reads_have_exact_source_ranges_and_ignore_comments():
    c='// A_(readCoeff("invented", dict))\n'+C
    schema=e.literal_input_schema(c,H)
    assert schema['keys']==['A','B'] and schema['dictionary']=='coeffs'
    lines=c.splitlines()
    assert 'readCoeff("A"' in lines[schema['start']-1]
    assert 'lookup<scalar>' in lines[schema['dictionary_source']['start']-1]
    assert e.literal_input_schema(C.replace('lookup<scalar>','lookupOrDefault<scalar>'),H) is None
    assert e.literal_input_schema(C,'/* '+H+' */') is None


def test_named_model_follows_selector_to_implementation(engine):
    directory=engine.skill/'corpus/manual/source_code/test';directory.mkdir(parents=True)
    (directory/'Demo.C').write_text(C);(directory/'Demo.H').write_text(H)
    b.k.build(SKILL,engine.skill/'corpus',engine.skill/'index')
    search=e.EditSearch(b.EvidenceSearch(b.build(engine.skill),engine.skill))
    packet=search.locate('sensor otherModel','caseA',budget=5000)
    schemas=[x for x in packet['locations'] if x['dictionary']=='otherModel/coeffs']
    assert schemas and schemas[0]['entries']==['coeffs/A','coeffs/B']
    assert 'subDict("coeffs")' in schemas[0]['dictionary_source']['text']
    assert any(x['relation']=='MODEL_INPUT_SCHEMA' and x['selector_entry'] for x in packet['relations'])
    assert not any(x['dictionary']=='otherModel/coeffs' for x in search.locate('sensor otherModel','caseA',graph=False)['locations'])
    assert not any(x['dictionary']=='otherModel/coeffs' for x in search.locate('sensor sampling','caseA')['locations'])


def test_removal_keys_do_not_recall_the_old_model_schema(engine):
    directory=engine.skill/'corpus/manual/source_code/test';directory.mkdir(parents=True)
    (directory/'Demo.C').write_text(C);(directory/'Demo.H').write_text(H)
    (directory/'Old.C').write_text(C.replace('Demo','Old').replace('"A"','"OldA"').replace('"B"','"OldB"'))
    (directory/'Old.H').write_text(H.replace('Demo','Old').replace('otherModel','sampling'))
    b.k.build(SKILL,engine.skill/'corpus',engine.skill/'index')
    search=e.EditSearch(b.EvidenceSearch(b.build(engine.skill),engine.skill))
    for verb in ('delete','remove','删除','保留'):
        packet=search.locate('sensor otherModel A=1 B=2; '+verb+' OldA OldB','caseA',budget=5000)
        assert any(x['dictionary']=='otherModel/coeffs' for x in packet['locations'])
        assert not any(x['dictionary']=='sampling/coeffs' for x in packet['locations'])


def test_preserved_object_and_redundant_type_are_not_edit_bindings(engine):
    root=engine.skill/'corpus';directory=root/'manual/source_code/test';directory.mkdir(parents=True)
    (directory/'Demo.C').write_text(C.replace('coeffs','thermodynamics'))
    (directory/'Demo.H').write_text(H)
    (root/'manual/markdown/01_sampling.md').write_text('# Models\n\n## 1.1 sampling\n\nThermal model.\n\n## 1.2 otherModel\n\nAlternate thermal model.\n')
    folder=root/'tutorials/caseA/constant';folder.mkdir()
    part='thermoType {thermo sampling;} thermodynamics {type sampling; A 1; B 2;}'
    (folder/'phaseProperties').write_text('FoamFile {version 2;} left {'+part+'} right {'+part+'}')
    b.k.build(SKILL,root,engine.skill/'index')
    search=e.EditSearch(b.EvidenceSearch(b.build(engine.skill),engine.skill))
    links=[x for x in search.graph['edges'] if x['relation']=='MODEL_INPUT_SCHEMA']
    assert links and all(x['selector_entry'].endswith('/thermoType/thermo') for x in links)
    for preserve in ('keep right thermodynamics A=1 B=2','right的thermodynamics参数全部保持原样',
                     'right的thermodynamics、数值设置和其余参数全部保持原样'):
        packet=search.locate('left otherModel A=4 B=7; '+preserve,'caseA',budget=6000)
        assert all(x['dictionary'].startswith('left/') for x in packet['locations'][:2])
