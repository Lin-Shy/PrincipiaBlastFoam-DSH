from types import SimpleNamespace
from experiments.retrieval_method.model_edit_draft import draft_model_edits


def fixture():
    nodes={'s':{'id':'s','case':'tutorials/demo','path':'tutorials/demo/constant/properties'},
           'c':{'id':'c','case':'tutorials/demo','path':'tutorials/demo/constant/coefficients','scope':'solid/settings'},
           'i':{'id':'i','model':'anotherModel','scope':'anotherModel/inputs','entries':[{'entry':'inputs/A'},{'entry':'inputs/B'}]}}
    edges=[{'relation':'MODEL_INPUT_SCHEMA','source':'s','target':'i','selector_entry':'solid/type'},
           {'relation':'SELECTOR_COEFFICIENTS','source':'s','target':'c','selector_entry':'solid/type'}]
    return SimpleNamespace(nodes=nodes,graph={'edges':edges}),{'case':'tutorials/demo','locations':[{'id':key} for key in nodes],'relations':[edges[0]]}


def test_draft_uses_bound_case_and_scope_without_air_or_model_name_assumptions():
    search,packet=fixture();result=draft_model_edits(search,packet,{'A':'2e-6','B':'42'})
    assert result['edits']==[
        {'path':'constant/properties','entry':'solid/type','value':'anotherModel'},
        {'path':'constant/coefficients','entry':'solid/settings/A','value':'2e-6'},
        {'path':'constant/coefficients','entry':'solid/settings/B','value':'42'}]


def test_draft_requires_explicit_finite_inputs_and_exposed_bindings():
    search,packet=fixture()
    assert draft_model_edits(search,packet,{'A':'1'})['status']=='missing_inputs'
    assert draft_model_edits(search,packet,{'A':'NaN','B':'1'})['status']=='invalid_scalar_input'
    packet['locations']=[{'id':'s'},{'id':'i'}]
    assert draft_model_edits(search,packet,{'A':'1','B':'2'})['edits']==[]


def test_draft_does_not_guess_between_multiple_model_bindings():
    search,packet=fixture();search.nodes['j']={**search.nodes['i'],'id':'j'}
    search.graph['edges'].append({**search.graph['edges'][0],'target':'j'})
    packet['locations'].append({'id':'j'})
    packet['relations'].append(search.graph['edges'][-1])
    assert draft_model_edits(search,packet,{'A':'1','B':'2'})['status']=='ambiguous_or_missing_model_binding'


def test_reverse_schema_neighbors_are_not_additional_edit_targets():
    search,packet=fixture()
    search.nodes['other']={**search.nodes['s'],'id':'other'}
    reverse={**search.graph['edges'][0],'source':'other'}
    search.graph['edges'].append(reverse)
    packet['locations'].append({'id':'other'})
    packet['relations'].append({**reverse,'traversal':'reverse'})
    result=draft_model_edits(search,packet,{'A':'1','B':'2'})
    assert result['status']=='draft_requires_review'
    assert result['support']['selector_node']=='s'
    packet['relations'][0]={**packet['relations'][0],'traversal':'reverse'}
    assert draft_model_edits(search,packet,{'A':'1','B':'2'})['edits']==[]


def test_optional_defaults_are_not_invented_or_required_and_conditions_block():
    search,packet=fixture()
    search.nodes['i']['entries'][1].update(requirement='optional',default_expression='external*A_')
    result=draft_model_edits(search,packet,{'A':'2'})
    assert result['status']=='draft_requires_review'
    assert len(result['edits'])==2 and result['edits'][-1]['entry']=='solid/settings/A'
    search.nodes['i']['entries'][1].update(requirement='conditional',conditions=[{'expression':'active'}])
    assert draft_model_edits(search,packet,{'A':'2','B':'3'})['status']=='unresolved_input_condition'
    search.nodes['i']['complete_local_reads']=False
    assert draft_model_edits(search,packet,{'A':'2','B':'3'})['status']=='incomplete_source_schema'


def test_unknown_stream_input_type_cannot_be_drafted_as_scalar():
    search,packet=fixture();search.nodes['i']['entries'][0]['value_type']=None
    assert draft_model_edits(search,packet,{'A':'2','B':'3'})['status']=='unsupported_input_type'
