import pytest
from test_evidence_bundle import engine
from test_condition_graph import index
import evidence_bundle as b
from condition_graph import ConditionalEditSearch
from experiments.retrieval_method.dependency_edit_draft import draft_dependency_edits


def fixture(engine):
    data=index(engine);rule=data['rules'][0]
    path='tutorials/caseA/system/controlDict';lines=(engine.skill/'corpus'/path).read_text().splitlines(keepends=True)
    line=next(i for i,text in enumerate(lines,1) if 'fields (p);' in text)
    rule['examples']=[{'path':path,'sha256':engine.graph['inventory'][path],'start':line,'end':line,'quote':lines[line-1]}]
    data['snapshot']=b.sha({k:v for k,v in data.items() if k!='snapshot'})
    binding={'condition_snapshot':data['snapshot'],'bindings':[{'id':'test','rule':rule['id'],'review':'accept','example_index':0,'source_parent':'functions/sensor','target_parents':['functions/first','functions/second']}]}
    binding['snapshot']=b.sha(binding)
    return ConditionalEditSearch(engine,data),{'conditions':[{'id':rule['id']}]},binding,rule['id']


def test_only_activated_exposed_reviewed_examples_produce_edits(engine):
    search,packet,bindings,rule=fixture(engine)
    assert not draft_dependency_edits(search,packet,[],bindings)['edits']
    assert not draft_dependency_edits(search,{'conditions':[]},[rule],bindings)['edits']
    result=draft_dependency_edits(search,packet,[rule],bindings)
    assert result['edits']==[{'path':'system/controlDict','entry':f'functions/{name}/fields','value':'(p)'} for name in ('first','second')]
    assert result['support'][0]['source']=='tutorials/caseA/system/controlDict'


def test_stale_or_unreviewed_bindings_do_not_generate_edits(engine):
    search,packet,bindings,rule=fixture(engine)
    bindings['condition_snapshot']='old';bindings['snapshot']=b.sha({k:v for k,v in bindings.items() if k!='snapshot'})
    with pytest.raises(ValueError,match='condition snapshot'):draft_dependency_edits(search,packet,[rule],bindings)
    search,packet,bindings,rule=fixture(engine)
    bindings['bindings'][0]['review']='reject';bindings['snapshot']=b.sha({k:v for k,v in bindings.items() if k!='snapshot'})
    assert not draft_dependency_edits(search,packet,[rule],bindings)['edits']


@pytest.mark.parametrize('values,status,expected',[
    ({'functions/first/solver':'PBiCGStab','functions/second/solver':'PBiCGStab'},'observed_not_validated',[]),
    ({'functions/first/solver':'PBiCGStab','functions/second/solver':'diagonal'},'observed_not_validated',['functions/second/fields']),
    ({'functions/first/solver':{'status':'lookup_failed'}},'observed_not_validated',[]),
    ({},'unsupported_directives',[]),
    ({},'file_absent',['functions/first/fields','functions/second/fields']),
])
def test_target_state_filters_reference_proposals(engine,values,status,expected):
    search,packet,bindings,rule=fixture(engine)
    search.index['rules'][0]['requirements']=[{'lookup_entries':['functions/first/solver','functions/second/solver'],'evidence':[]}]
    search.index['snapshot']=b.sha({k:v for k,v in search.index.items() if k!='snapshot'})
    bindings['condition_snapshot']=search.index['snapshot']
    bindings['bindings'][0].update(lookup_requirement=0,target_state_policy={'selector':'solver','replace_values':['diagonal']})
    bindings['snapshot']=b.sha({k:v for k,v in bindings.items() if k!='snapshot'})
    packet['conditions'][0]['requirements']=[{'lookup_state':{'status':status,'values':values}}]
    result=draft_dependency_edits(search,packet,[rule],bindings)
    assert [x['entry'] for x in result['edits']]==expected
    assert len(result['target_states'])==2
