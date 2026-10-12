import pytest
from experiments.retrieval_method.combination_graph import extract,build,lookup


def source():
    text=''
    for cls,label in [('Phase','phaseFluid'),('Basic','basic'),('Specie','specie')]:
        text+='class '+cls+' { static const char* typeName_() { return "'+label+'"; } };\n'
    for cls,label in [('Transport','const'),('Thermo','hConst'),('EOS','idealGas')]:
        text+='class '+cls+' { static word typeName() { return "'+label+'<" + T::typeName() + \'>\'; } };\n'
    return text+('typedef Transport<thermoModel<Thermo<EOS<Specie>>>> Physics;\n'
                 'typedef Basic<Energy<Phase,Physics>> Wrapped;\n'
                 'Phase::adddictionaryConstructorToTable<Wrapped> registration;\n')


def test_complete_registration_chain_and_literal_runtime_names():
    found=extract(source());assert found['observed_registration_declarations']==1
    assert not found['unresolved_registrations'];record=found['records'][0]
    assert record['combination']=='phaseFluid<basic<const<hConst<idealGas<specie>>>>>'
    graph=build(found,{'expanded_sha256':'fixture'})
    packet=lookup(graph,record['components']);assert len(packet['evidence_groups'])==1
    assert packet['status']=='source_registration_declaration'
    assert lookup(graph,{**record['components'],'thermo':'ePower'})['status']=='not_observed_in_indexed_translation_units'


def test_alias_without_registration_does_not_prove_registration():
    assert extract(source().replace('Phase::adddictionaryConstructorToTable<Wrapped> registration;',''))['records']==[]
    found=extract(source().replace('Table<Wrapped>','Table<Missing>'))
    assert not found['records'] and len(found['unresolved_registrations'])==1


def test_mismatched_registration_base_and_ambiguous_names_are_unresolved():
    assert not extract(source().replace('Phase::adddictionary','Other::adddictionary'))['records']
    assert not extract(source()+'class Thermo { static word typeName() { return "different"; } };')['records']


def test_changed_graph_is_rejected():
    graph=build(extract(source()),{});graph['limits']='silently claim build success'
    with pytest.raises(ValueError,match='changed'):lookup(graph,{})
