import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments/retrieval_method'))
import leaderboard_admission as admission
import leaderboard_audit as audit
import navigation_qa as qa


def fixture(root):
    audit.save(root/'protocol.json',{'files':{},'groups':{'control':['no_graph']},'replicates':1,'model':'fixture'})
    audit.save(root/'control/questions.json',[{'id':'Q'}])
    folder=root/'control/sessions/Q--no_graph--r1'
    audit.save(folder/'result.json',{'returned_characters':0,'events':[]})
    body={'model':'fixture','temperature':0,'thinking':{'type':'disabled'},'max_tokens':2400}
    audit.save(folder/'final.json',{'request':body,'request_sha256':qa.digest(qa.wire(body)),
        'events':[{'status':'response'}],'raw_response':{'model':'fixture','system_fingerprint':'f'}})
    return folder


def test_missing_or_stale_replay_does_not_admit_complete_answers(tmp_path):
    folder=fixture(tmp_path)
    assert not admission.check(tmp_path)['passed']
    audit.save(folder/'invocations/1.json',{'replay':True,'status':'complete','started_unix_ns':0})
    assert not admission.check(tmp_path)['passed']
    audit.save(folder/'invocations/2.json',{'replay':True,'status':'complete',
        'started_unix_ns':(folder/'result.json').stat().st_mtime_ns+1})
    assert admission.check(tmp_path)['passed']


def test_changed_request_body_cannot_reuse_request_identity(tmp_path):
    import pytest
    folder=fixture(tmp_path);p=folder/'final.json';r=audit.read(p)
    r['request']['max_tokens']=9000;audit.save(p,r)
    with pytest.raises(ValueError,match='request identity'):admission.check(tmp_path)


def test_complete_root_replay_admits_runner_without_session_marker(tmp_path):
    folder=fixture(tmp_path)
    started=(folder/'result.json').stat().st_mtime_ns+1
    audit.save(tmp_path/f'invocations/{started}.json',{
        'command':'replay','state':'finished','jobs':1,'completed':1,'errors':[]})
    result=admission.check(tmp_path)
    assert result['passed']
    assert result['replayed']==1
    assert result['complete_root_replay']==f'invocations/{started}.json'


def test_stale_or_partial_root_replay_does_not_admit(tmp_path):
    folder=fixture(tmp_path)
    stale=max(1,(folder/'result.json').stat().st_mtime_ns-1)
    audit.save(tmp_path/f'invocations/{stale}.json',{
        'command':'replay','state':'finished','jobs':1,'completed':1,'errors':[]})
    assert not admission.check(tmp_path)['passed']
    fresh=(folder/'result.json').stat().st_mtime_ns+1
    audit.save(tmp_path/f'invocations/{fresh}.json',{
        'command':'replay','state':'finished','jobs':1,'completed':0,'errors':[]})
    assert not admission.check(tmp_path)['passed']


def test_only_exhausted_frozen_failure_can_complete_grid_without_answer(tmp_path):
    folder=fixture(tmp_path)
    audit.save(folder/'invocations/2.json',{'replay':True,'status':'complete',
        'started_unix_ns':(folder/'result.json').stat().st_mtime_ns+1})
    audit.save(tmp_path/'control/questions.json',[{'id':'Q'},{'id':'Q2'}])
    failure=tmp_path/'control/sessions/Q2--no_graph--r1/step-01.json'
    record=audit.read(folder/'final.json');record.pop('raw_response')
    record['request']['max_tokens']=700;record['request_sha256']=qa.digest(qa.wire(record['request']))
    record.update(status='transport_error',events=[{'status':'transport_error'}]*3)
    audit.save(failure,record)
    assert not admission.check(tmp_path)['passed']
    record['events']*=3;audit.save(failure,record)
    result=admission.check(tmp_path)
    assert result['passed'] and result['answers']==1 and result['terminal_failures']==1


def test_protocol_can_freeze_a_larger_explicit_model_budget(tmp_path):
    folder=fixture(tmp_path)
    protocol=audit.read(tmp_path/'protocol.json')
    protocol.update(maximum_model_calls=10,maximum_generated_tokens=8700)
    audit.save(tmp_path/'protocol.json',protocol)
    template=audit.read(folder/'final.json')
    template['request']['max_tokens']=700
    template['request_sha256']=qa.digest(qa.wire(template['request']))
    for index in range(1,10):
        audit.save(folder/f'step-{index:02}.json',template)
    audit.save(folder/'invocations/2.json',{'replay':True,'status':'complete',
        'started_unix_ns':(folder/'result.json').stat().st_mtime_ns+1})
    result=admission.check(tmp_path)
    assert result['passed']
    assert result['maximum_model_calls']==10
    assert result['maximum_generated_tokens']==8700
