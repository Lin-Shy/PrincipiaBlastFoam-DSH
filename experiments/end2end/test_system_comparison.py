import importlib.util
from pathlib import Path
import types
import pytest

HERE=Path(__file__).resolve().parent
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
bridge=load('cluster_bridge',HERE/'cluster_job.py')
def cfg():return {'partition':'debug','tasks':1,'wall_minutes':5,'memory_mib':2048,'openfoam_bashrc':'/readonly/of/etc/bashrc','blastfoam_bashrc':'/readonly/blast/etc/bashrc','ssh_config':'operator.config','ssh_target':'cluster'}
def grant(action):return {'live_actions_allowed':True,'run_ids':['c3-test'],'actions':[action],'limits':{'tasks':1,'wall_minutes':5,'memory_mib':2048}}

def test_live_denied_before_process_or_write(tmp_path,monkeypatch):
    monkeypatch.setattr(bridge.subprocess,'run',lambda *a,**kw:pytest.fail('must not launch'))
    for action in ['stage','submit','status','collect']:
        with pytest.raises(PermissionError):bridge.run(action,cfg(),'c3-test',tmp_path/'state',grant={})
    assert not (tmp_path/'state').exists()

def test_scheduler_plan_and_scope():
    plan=bridge.plan(cfg(),'c3-general-s10-01')
    assert plan['submit_argv'][0]=='yhbatch'
    assert 'scontrol show hostnames' in plan['batch_script'] and 'payload/run_case.sh' in plan['batch_script']
    for value in ['../other','c4-other','c3-a; rm']:
        with pytest.raises(ValueError):bridge.plan(cfg(),value)

def test_resource_grant_does_not_expand():
    approval=grant('submit');approval['limits']['wall_minutes']=4
    with pytest.raises(PermissionError):bridge.authorize(cfg(),approval,'c3-test','submit')

def test_submit_receipt_and_no_double_submit(tmp_path,monkeypatch):
    spec=bridge.plan(cfg(),'c3-test');bridge.write(tmp_path/'stage_receipt.json',{'run_id':'c3-test','remote':spec['remote']})
    commands=[]
    def fake(config,command,**kw):commands.append(command);return types.SimpleNamespace(stdout='Submitted batch job 12345\n')
    monkeypatch.setattr(bridge,'ssh',fake)
    result=bridge.run('submit',cfg(),'c3-test',tmp_path,grant=grant('submit'))
    assert result['job_id']=='12345' and commands[0].startswith('yhbatch ')
    with pytest.raises(FileExistsError):bridge.run('submit',cfg(),'c3-test',tmp_path,grant=grant('submit'))
    assert len(commands)==1

def test_foreign_job_receipt_rejected(tmp_path,monkeypatch):
    bridge.write(tmp_path/'job_receipt.json',{'run_id':'c3-other','remote':'/other','job_id':'1'})
    monkeypatch.setattr(bridge,'ssh',lambda *a,**kw:pytest.fail('foreign job query'))
    with pytest.raises(ValueError):bridge.run('status',cfg(),'c3-test',tmp_path,grant=grant('status'))

def test_domain_missing_window_not_fabricated(tmp_path,monkeypatch):
    monkeypatch.syspath_prepend(str(HERE));module=load('observe_cli',HERE/'professional/observe.py')
    raw=tmp_path/'p';raw.write_text('0 100000\n0.001 101000\n')
    result=module.analyze(raw,100000,0,.003)
    assert result['status']=='incomplete_window' and result['metrics'] is None
    good=module.analyze(raw,100000,0,.001)
    assert good['metrics'][0]['whole_window_positive_area_pa_s']==pytest.approx(.5)
    with pytest.raises(ValueError):module.analyze(raw,100000,1,0)
    with pytest.raises(ValueError):module.analyze(raw,float('nan'),0,.001)

def test_mock_transport_stage_submit_query_collect(tmp_path,monkeypatch):
    payload=tmp_path/'payload';payload.mkdir();(payload/'run_case.sh').write_text('true\n')
    state=tmp_path/'state';config=cfg();config['hpc_entry']='operator-hpc.py'
    calls=[]
    monkeypatch.setattr(bridge.subprocess,'run',lambda args,**kw:calls.append(args))
    def fake(config,command,**kw):
        calls.append(command)
        if 'sha256sum' in command:return types.SimpleNamespace(stdout=bridge.digest(state/'payload.tar')+'  payload.tar')
        if command.startswith('yhbatch'):return types.SimpleNamespace(stdout='Submitted batch job 12345\n')
        if command.startswith('scontrol'):return types.SimpleNamespace(stdout='JobId=12345 JobState=COMPLETED')
        if command.startswith('tar -C'):kw['stdout'].write(b'mocked archive bytes')
        return types.SimpleNamespace(stdout='')
    monkeypatch.setattr(bridge,'ssh',fake)
    for action in ['stage','submit','status','collect']:
        result=bridge.run(action,config,'c3-test',state,payload,grant(action))
        if action=='status':assert result['scientific_success']=='not_assessed'
    assert (state/'collection_receipt.json').exists()
    assert result['bytes']==len(b'mocked archive bytes')
    assert len(calls)==7

def test_collection_retry_preserves_partial_without_new_job(tmp_path,monkeypatch):
    spec=bridge.plan(cfg(),'c3-test')
    bridge.write(tmp_path/'job_receipt.json',{'run_id':'c3-test','remote':spec['remote'],'job_id':'123'})
    def broken(config,command,**kw):
        kw['stdout'].write(b'partial');raise TimeoutError('transport')
    monkeypatch.setattr(bridge,'ssh',broken)
    with pytest.raises(TimeoutError):bridge.run('collect',cfg(),'c3-test',tmp_path,grant=grant('collect'))
    assert not (tmp_path/'collection_receipt.json').exists()
    assert (tmp_path/'collection-001.partial.tar').read_bytes()==b'partial'
    monkeypatch.setattr(bridge,'ssh',lambda config,command,**kw:kw['stdout'].write(b'complete transport fixture'))
    result=bridge.run('collect',cfg(),'c3-test',tmp_path,grant=grant('collect'))
    assert result['job_id']=='123' and (tmp_path/'collected.tar').exists()
    assert (tmp_path/'collection-001.partial.tar').read_bytes()==b'partial'
