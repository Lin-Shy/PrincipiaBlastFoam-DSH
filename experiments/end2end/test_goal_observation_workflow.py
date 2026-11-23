import hashlib
import json
from pathlib import Path
import pytest
from experiments.end2end.goal_observation_workflow import Workflow, sampling_plan


@pytest.fixture
def setup(tmp_path):
    root=tmp_path/'input';root.mkdir();p=root/'p'
    p.write_text('# Probe 0 (0 0 0)\n0 99\n1 101\n2 99\n')
    task=dict(id='test',sampling_kind='point_static',interpolation='cellPoint',ambient_pa=100,required_window_s=[0,2],sensors=[{'id':'A','position_m':[0,0,0]}])
    query=dict(id='q1',window_s=[0,2],sensors=['A'],observables=['peak_overpressure_pa','whole_window_positive_area_pa_s'])
    return root,p,task,query,hashlib.sha256(p.read_bytes()).hexdigest()


def test_construct_collect_deliver_independent_oracle(setup,tmp_path):
    root,p,t,q,sha=setup;w=Workflow(root,tmp_path/'out',cache=True,goal_state=True)
    result=w.run(t,q,p,sha)
    assert [c['value'] for c in result['claims']]==[1.,.5]
    assert result['check']['mismatches']==[]
    assert (tmp_path/'out/q1/functions.fragment').is_file()
    assert json.loads((tmp_path/'out/q1/configuration.json').read_text())['status']=='draft_not_executed'


def test_display_change_reuses_features_without_changing_SI(setup,tmp_path):
    root,p,t,q,sha=setup;w=Workflow(root,tmp_path/'out',cache=True,goal_state=True)
    a=w.run(t,q,p,sha);q={**q,'id':'q2','display_units':'kPa/ms'};b=w.run(t,q,p,sha)
    assert a['claims']==b['claims']
    assert w.cost['extraction_evaluations']==1
    assert w.cost['extraction_tool_calls']==1 and w.cost['extraction_dispatch_skips']==1
    graph=json.loads((tmp_path/'out/q2/delivery.json').read_text())['goal_state']
    assert graph['changed_nodes']==['delivery']


def test_missing_window_and_first_pulse_remain_unknown(setup,tmp_path):
    root,p,t,q,sha=setup;t['required_window_s']=[0,3];q['window_s']=[0,3]
    q['observables'].append('first_incident_pulse_peak')
    r=Workflow(root,tmp_path/'out').run(t,q,p,sha)
    assert all(c['status']=='unknown' for c in r['claims'])
    assert r['check']['mismatches']==[] and r['check']['unknown_count']==3


def test_supported_output_survives_unsupported_sibling(setup,tmp_path):
    root,p,t,q,sha=setup;q['observables'].append('first_incident_pulse_peak')
    r=Workflow(root,tmp_path/'out').run(t,q,p,sha)
    assert [c['status'] for c in r['claims']]==['available','available','unknown']


def test_scope_and_stale_source_cannot_be_hidden_by_cache(setup,tmp_path):
    root,p,t,q,sha=setup;w=Workflow(root,tmp_path/'out',cache=True)
    w.run(t,q,p,sha);q['id']='q2';p.write_text(p.read_text().replace('101','102'))
    with pytest.raises(ValueError,match='changed'):w.run(t,q,p,sha)
    other=tmp_path/'other';other.write_text('private')
    with pytest.raises(ValueError,match='outside'):w.run(t,q,other,sha)
    q['id']='../escape'
    with pytest.raises(ValueError,match='identifier'):w.run(t,q,p,sha)


def test_patch_draft_requires_patch_and_preserves_task_end(setup):
    _,_,t,_,_=setup;t.update(sampling_kind='patch_static',patch='ground')
    p=sampling_plan(t)
    assert 'patchProbes' in p['functions_fragment'] and p['required_end_time_s']==2
    t['patch']='ground; injected'
    with pytest.raises(ValueError):sampling_plan(t)
