"""Conditional requirements preserve reviewed evidence and alternative semantics."""
from test_evidence_bundle import engine
import evidence_bundle as b
from condition_graph import ConditionalEditSearch,validate
import pytest


def test_reviewed_lookup_observes_regex_and_exact_override(tmp_path):
    import shutil
    if not shutil.which('foamDictionary'):pytest.skip('OpenFOAM required')
    from condition_graph import lookup_observations
    (tmp_path/'system').mkdir();p=tmp_path/'system/fvSolution'
    p.write_text('solvers { "(U|e)" {solver PBiCGStab;} ".*" {solver diagonal;} }')
    req={'target':'system/fvSolution','lookup_entries':['solvers/U/solver','solvers/e/solver']}
    first=lookup_observations(req,tmp_path)['lookup_state']
    assert set(first['values'].values())=={'diagonal'}
    p.write_text('solvers { ".*" {solver diagonal;} U {solver PCG;} e {solver PBiCGStab;} }')
    second=lookup_observations(req,tmp_path)['lookup_state']
    assert second['values']=={'solvers/U/solver':'PCG','solvers/e/solver':'PBiCGStab'}
    assert first['sha256']!=second['sha256']
    p.write_text('#include "outside"')
    assert lookup_observations(req,tmp_path)['lookup_state']['status']=='unsupported_directives'


def index(engine):
    path='manual/markdown/01_sampling.md'
    rule={'id':'sampling-input','dictionary_patterns':['functions/sensor'],
       'when':'sampling requires configured fields','required_files':['system/controlDict','system/alternate'],
       'required_files_semantics':'alternatives, not both required',
       'evidence':[{'path':path,'start':5,'end':5,'quote':'The sampled quantity is configured in fields.',
                    'sha256':engine.graph['inventory'][path]}],
       'examples':[],'review':{'status':'accept'}}
    data={'rules':[rule]};data['snapshot']=b.sha(data);return data


def test_conditions_are_unresolved_and_only_returned_with_graph(engine):
    data=index(engine);search=ConditionalEditSearch(engine,data)
    packet=search.locate('sampling fields sensor','caseA',budget=4000)
    assert packet['conditions'][0]['condition_evaluation']=='not_evaluated'
    assert packet['conditions'][0]['required_files_semantics']=='alternatives, not both required'
    assert [x['present_in_template'] for x in packet['conditions'][0]['required_files']]==[True,False]
    assert len(b.wire(packet))<=4000
    plain=search.locate('sampling fields sensor','caseA',budget=4000,graph=False)
    assert 'conditions' not in plain
    small=search.locate('sampling fields sensor','caseA',budget=1000)
    assert len(b.wire(small))<=1000


def test_runtime_guard_requires_matching_reviewed_source_condition(engine):
    path='manual/source_code/gate.C';raw='if (max(mu) > small) { createModels(); }\n'
    file=engine.skill/'corpus'/path;file.parent.mkdir(parents=True,exist_ok=True);file.write_text(raw)
    engine.graph['inventory'][path]=b.sha(raw.encode())
    engine.graph['snapshot']=b.sha({k:v for k,v in engine.graph.items() if k!='snapshot'})
    data=index(engine);guard={'expression':'max(mu) > small','review':'accept',
        'evidence':[{'path':path,'start':1,'end':1,'quote':raw,'sha256':engine.graph['inventory'][path]}]}
    data['rules'][0]['runtime_guard']=guard
    def check():
        data['snapshot']=b.sha({k:v for k,v in data.items() if k!='snapshot'})
        return validate(data,engine)
    assert check()[0]['runtime_guard']['expression']=='max(mu) > small'
    preparation={'relation':'PREPARES_FOR','review':'accept','when':'Prepare requested branch; runtime remains unknown.',
                 'evidence':data['rules'][0]['evidence']}
    data['rules'][0]['preparation']=preparation
    check()
    packet=ConditionalEditSearch(engine,data).locate('sampling fields sensor','caseA',budget=4000)
    assert packet['conditions'][0]['preparation']['relation']=='PREPARES_FOR'
    assert packet['conditions'][0]['condition_evaluation']=='not_evaluated'
    preparation['review']='pending'
    with pytest.raises(ValueError,match='preparation'):check()
    preparation['review']='accept'
    guard['expression']='max(mu) > 0'
    with pytest.raises(ValueError,match='runtime guard'):check()
    guard['evidence'][0]['quote']='if (max(mu) > 0) { createModels(); }'
    with pytest.raises(ValueError,match='quote'):check()
    guard['expression']='max(mu) > small';guard['evidence'][0]['quote']=raw;guard['review']='pending'
    with pytest.raises(ValueError,match='runtime guard'):check()


def test_source_or_review_failure_cannot_be_silently_accepted(engine):
    data=index(engine);data['rules'][0]['evidence'][0]['quote']='invented'
    with pytest.raises(ValueError,match='digest'):validate(data,engine)
    data['snapshot']=b.sha({k:v for k,v in data.items() if k!='snapshot'})
    with pytest.raises(ValueError,match='quote'):validate(data,engine)
    data=index(engine);data['rules'][0]['review']['status']='reject'
    data['snapshot']=b.sha({k:v for k,v in data.items() if k!='snapshot'})
    assert not validate(data,engine)


def test_example_diff_uses_complete_reviewed_entries_and_exact_paths(engine):
    from condition_graph import example_differences
    path='tutorials/caseA/system/controlDict'
    lines=(engine.skill/'corpus'/path).read_text().splitlines(keepends=True)
    start=next(i for i,line in enumerate(lines,1) if 'fields (p);' in line)
    ev={'path':path,'start':start,'end':start,'quote':lines[start-1]}
    assert not example_differences({'examples':[ev]},engine,'tutorials/caseA')
    diff=example_differences({'examples':[ev]},engine,'tutorials/missingCase')
    assert diff[0]['entries']==[{'entry':'functions/sensor/fields','example_value':'(p)','target_value':None}]
    assert 'not_required_change' in diff[0]['status']


def test_requirement_source_links_are_deduplicated_and_checked(engine):
    from condition_graph import requirement_packet
    data=index(engine);rule=data['rules'][0];ev=rule['evidence'][0]
    rule['requirements']=[{'target':'a','entry':'x','requirement':'first','evidence':[ev]},
                          {'target':'b','entry':'y','requirement':'second','evidence':[ev]}]
    packet=requirement_packet(rule)
    assert len(packet['code_sources'])==1
    assert packet['requirements'][0]['support']==packet['requirements'][1]['support']
    data['snapshot']=b.sha({k:v for k,v in data.items() if k!='snapshot'})
    assert validate(data,engine)


def test_state_binding_reads_edited_copy_and_never_predicts_nonconstant_models(engine,tmp_path):
    data=index(engine);rule=data['rules'][0]
    rule['case_patterns']=['tutorials/caseA']
    rule['state_binding']={'predicate':'explicit_const_zero_excludes_viscosity','application':'blastFoam',
                           'review':{'status':'accept'},'evidence':rule['evidence']}
    rule['requirements']=[{'target':'system/fvSolution','entry':'solvers/U',
                          'requirement':'conditional solver','evidence':rule['evidence']}]
    data['snapshot']=b.sha({k:v for k,v in data.items() if k!='snapshot'})
    folder=tmp_path/'constant';folder.mkdir();path=folder/'phaseProperties'
    (tmp_path/'system').mkdir();(tmp_path/'system/controlDict').write_text('application blastFoam;')
    text='phases (gas); gas {type basic; thermoType {transport const;} transport {mu 0;}}'
    path.write_text(text);search=ConditionalEditSearch(engine,data)
    a=search.assess_case(tmp_path,'caseA')['conditions'][0]
    assert a['condition_evaluation']=='inactive_for_current_inputs' and not a['requirements']
    for changed in [text.replace('mu 0','mu 1e-5'),text.replace('transport const','transport sutherland')]:
        path.write_text(changed);z=search.assess_case(tmp_path,'caseA')['conditions'][0]
        assert z['condition_evaluation']=='not_evaluated' and z['requirements']
        assert z['state']['sha256']!=a['state']['sha256']
    small=search.assess_case(tmp_path,'caseA',budget=1000)
    assert len(b.wire(small))<=1000 and small['status']!='ok'
    path.write_text(text);(tmp_path/'system/controlDict').write_text('application otherSolver;')
    assert search.assess_case(tmp_path,'caseA')['conditions'][0]['condition_evaluation']=='not_evaluated'


def test_unreviewed_state_binding_cannot_prune_requirements(engine,tmp_path):
    data=index(engine)
    assert not ConditionalEditSearch(engine,data).assess_case(tmp_path,'caseA')['conditions']


def test_control_semantics_does_not_imply_new_files(engine):
    data=index(engine);rule=data['rules'][0]
    rule['relation']='DESCRIBES_CONTROL';rule['required_files']=[]
    rule['required_files_semantics']='existing keys; no new file implied'
    data['snapshot']=b.sha({k:v for k,v in data.items() if k!='snapshot'})
    packet=ConditionalEditSearch(engine,data).locate('sensor sampling fields','caseA',budget=4000)
    assert packet['conditions'][0]['relation']=='DESCRIBES_CONTROL'
    assert packet['conditions'][0]['required_files']==[]


def test_incidental_third_location_does_not_activate_a_rule(engine,monkeypatch):
    search=ConditionalEditSearch(engine,index(engine))
    packet={'case':'tutorials/caseA','locations':[
        {'path':'tutorials/caseA/system/controlDict','dictionary':scope}
        for scope in ('','other','functions/sensor')]}
    monkeypatch.setattr(search.search,'locate',lambda *a,**k:packet)
    assert 'conditions' not in search.locate('change another setting','caseA')


def test_reviewed_summary_cannot_hide_broken_underlying_source(engine):
    data=index(engine)
    data['rules'][0]['review_sources']=[{**data['rules'][0]['evidence'][0],'quote':'unverified underlying source'}]
    data['snapshot']=b.sha({k:v for k,v in data.items() if k!='snapshot'})
    with pytest.raises(ValueError,match='quote'):validate(data,engine)
