import json
from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).parent))
from model_budget import Gate
from launch_attempt import check

def response():
    return b'data: {"choices":[],"usage":{"prompt_tokens":8,"completion_tokens":2,"total_tokens":10}}\n\ndata: [DONE]\n\n'

def test_request_cap_and_model_binding(tmp_path):
    requests=[]
    def forward(body):requests.append(body);return response()
    gate=Gate(tmp_path/'gate','same-model',1,10,forward)
    with pytest.raises(ValueError):gate.call({'model':'other'})
    gate.call({'model':'same-model','max_tokens':3})
    with pytest.raises(ValueError):gate.call({'model':'same-model'})
    assert len(requests)==1 and requests[0]['max_tokens']==3
    assert gate.events[0]['usage']['total_tokens']==10

def test_unknown_usage_stops_without_refund(tmp_path):
    gate=Gate(tmp_path/'gate','m',3,10,lambda body:b'data: [DONE]\n\n')
    with pytest.raises(ValueError):gate.call({'model':'m'})
    assert gate.closed and gate.events[0]['state']=='unknown'
    with pytest.raises(ValueError):gate.call({'model':'m'})
    assert len(gate.events)==1

def test_launcher_denies_unapproved_pair_before_credentials(tmp_path):
    (tmp_path/'manifest.json').write_text('{}')
    with pytest.raises(PermissionError):check(tmp_path,'general',{}, {})

def test_public_s12_has_no_reference_rows(tmp_path):
    from prepare_system_comparison import WS,write,copy
    from public_s12 import prepare
    prepare(tmp_path,WS,{},copy,write)
    spec=json.loads((tmp_path/'specification.json').read_text())
    assert 'comparison' not in spec and 'reference_rows' not in spec
    assert spec['source']['full_sphere_mass_kg']==1
    assert len(json.loads((tmp_path/'conditions.json').read_text())['probe_radii_m'])==13
    assert (tmp_path/'initialization/initialize_wedge_source.py').exists()

def test_review_recomputes_without_claiming_success(tmp_path):
    from review_delivery import inspect
    task=tmp_path/'task';task.mkdir();delivery=tmp_path/'delivery';delivery.mkdir()
    (task/'conditions.json').write_text(json.dumps({'probe_locations_m':[[0,1,0]],'metric_window_s':[0,.001],'ambient_pa':100000}))
    (delivery/'p').write_text('0 100000\n0.001 101000\n')
    (delivery/'observations.json').write_text(json.dumps({'records':[{'sensor_id':'P1','raw_file':'p','column':0}]}))
    result=inspect(task,delivery)
    assert result['raw_window_complete']
    assert result['raw_recomputed_metrics'][0]['metrics']['whole_window_positive_area_pa_s']==pytest.approx(.5)
    assert result['engineering_delivery_complete'] is None and result['prediction_accuracy']=='pending'
    (delivery/'p').write_text('0.0001 100000\n0.001 101000\n')
    assert not inspect(task,delivery)['raw_window_complete']

def test_cluster_service_cannot_change_run_or_payload_scope(tmp_path,monkeypatch):
    from cluster_service import Service
    import cluster_service
    workspace=tmp_path/'work';workspace.mkdir();seen=[]
    service=Service(workspace,tmp_path/'state',{}, {},'c3-fixed')
    def fixed(action,config,run_id,state,payload,grant):seen.append(run_id);return {'run_id':run_id}
    monkeypatch.setattr(cluster_service.cluster_job,'run',fixed)
    with pytest.raises(ValueError):service.execute({'action':'plan','run_id':'c4-other'})
    with pytest.raises(ValueError):service.execute({'action':'stage','payload':'../other'})
    assert service.execute({'action':'plan'})['run_id']=='c3-fixed' and seen==['c3-fixed']

def test_dedicated_endpoint_identity_is_scoped(tmp_path):
    import hashlib
    (tmp_path/'manifest.json').write_text('{}')
    binding={'base_url_source':'dedicated_file','endpoint_sha256':'fixture-id','model':'m','context_window':32768,'runtime':'fixture','credential_file':'fixture'}
    grant={'live_model_allowed':True,'arms':['general'],'pair_manifest_sha256':hashlib.sha256(b'{}').hexdigest(),'authorization_evidence':'fixture','isolation_accepted':True,'isolation_evidence':'fixture','budget_unit':'requests','max_requests_per_arm':1,'max_output_tokens':100,'wall_seconds':10,'model':'m','context_window':32768,'endpoint_sha256':'fixture-id'}
    check(tmp_path,'general',binding,grant)
    grant['endpoint_sha256']='different'
    with pytest.raises(PermissionError):check(tmp_path,'general',binding,grant)


def test_pilot_generation_binding_overrides_agent(tmp_path):
    sent=[]
    g=Gate(tmp_path/'fixed','m',1,10,lambda b:(sent.append(b) or response()),{'temperature':0,'top_p':1,'thinking':{'type':'disabled'}})
    g.call({'model':'m','temperature':2,'max_tokens':100})
    assert sent[0]['temperature']==0 and sent[0]['max_tokens']==10
    assert sent[0]['thinking']=={'type':'disabled'}


def test_pinned_runtime_environment_and_no_requeue():
    from cluster_job import plan
    config={'partition':'deimos','tasks':64,'wall_minutes':90,'memory_mib':512000,'exclusive':True,
        'runtime_environment':{'OMPI_MCA_mca_base_component_path':'/readonly/mpi'},'runtime_sha256':{'/readonly/solver':'a'*64}}
    p=plan(config,'c3-pilot-test')
    assert '--no-requeue' in p['submit_argv'] and '--export=NONE' in p['submit_argv']
    assert 'source ' not in p['batch_script'] and 'sha256sum /readonly/solver' in p['batch_script']
    assert 'export OMPI_MCA_mca_base_component_path=/readonly/mpi' in p['batch_script']
