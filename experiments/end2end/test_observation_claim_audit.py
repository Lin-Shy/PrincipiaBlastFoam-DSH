import hashlib
import pytest
from experiments.end2end.observation_claim_audit import audit_claim


@pytest.fixture
def fixture(tmp_path):
    p=tmp_path/'p'
    p.write_text('0 100000\n1 102000\n2 100000\n')
    digest=hashlib.sha256(p.read_bytes()).hexdigest()
    request=dict(observable='whole_window_peak_overpressure',gauge='A',window_s=[0,2],time_origin='simulation',target_position_m=[0,0,0],position_tolerance_m=0.)
    claim={k:request[k] for k in ['observable','gauge','window_s','time_origin']}
    claim.update(value=2.,unit='kPa',source_sha256=digest)
    binding=dict(sha256=digest,pressure_kind='absolute',unit='Pa',ambient_pa=100000,time_unit='s',time_origin='simulation',gauges={'A':{'column':0,'actual_position_m':[0,0,0]}})
    return p,request,claim,binding


def test_known_peak_and_declared_wrong_unit(fixture):
    p,r,c,b=fixture
    assert audit_claim(p,r,c,b)['computed_pa']==2000
    c['unit']='Pa'
    assert audit_claim(p,r,c,b,level='declared')['status']=='consistent'
    assert audit_claim(p,r,c,b)['status']=='reject'


def test_forged_anchor_is_outside_guarantee(fixture):
    p,r,c,b=fixture
    b['ambient_pa']=99000;c['value']=3.
    assert audit_claim(p,r,c,b)['status']=='consistent'
    assert audit_claim(p,r,c,b)['task_success'] is None


@pytest.mark.parametrize('bad',[float('nan'),float('inf'),-1])
def test_nonfinite_or_negative_position_tolerance_is_unknown(fixture,bad):
    p,r,c,b=fixture;r['position_tolerance_m']=bad
    assert audit_claim(p,r,c,b)['status']=='unknown'


def test_first_pulse_not_implicitly_global_max(fixture):
    p,r,c,b=fixture;r['observable']=c['observable']='first_incident_pulse_peak'
    assert audit_claim(p,r,c,b)['status']=='unknown'


def test_unknown_and_stale_are_distinct(fixture):
    p,r,c,b=fixture
    assert audit_claim(p,r,c,None)['status']=='unknown'
    p.write_text('0 100000\n1 103000\n2 100000\n')
    assert audit_claim(p,r,c,b)['status']=='reject'
