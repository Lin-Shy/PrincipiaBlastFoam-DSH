from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments/retrieval_method'))
from chapter2_generation_circuit import wrap_scheduler, ORIGINAL_SIGNAL


def execute(tmp_path,rows):
    seen=[];scheduler_arguments=[]
    def scheduler(items,worker,observe,**kwargs):
        scheduler_arguments.append(kwargs)
        for item in items:observe(item,worker(item))
    def observe(item,result):
        seen.append(item)
        if result['status']!='answered':raise RuntimeError(ORIGINAL_SIGNAL)
    wrapped=wrap_scheduler(scheduler,tmp_path/'admission.jsonl','a'*64)
    items=[dict(model=model,result=result) for model,result in rows]
    wrapped(items,lambda row:row['result'],observe,model_of=lambda row:row['model'],workers_per_model=16)
    return seen,scheduler_arguments


def test_isolated_failure_is_retained_once_and_models_are_independent(tmp_path):
    rows=[('8b',dict(status='transport_error')),('14b',dict(status='transport_error')),
          ('8b',dict(status='answered')),('14b',dict(status='answered'))]
    seen,args=execute(tmp_path,rows)
    assert len(seen)==4 and args[0]['workers_per_model']==16
    assert 'retain_isolated_failure_and_admit_unattempted' in (tmp_path/'admission.jsonl').read_text()


@pytest.mark.parametrize('statuses',[
    ['transport_error','transport_error'],
    ['transport_error','answered','transport_error','answered','transport_error']])
def test_consecutive_or_rolling_failure_threshold_stops(tmp_path,statuses):
    with pytest.raises(RuntimeError,match=ORIGINAL_SIGNAL):execute(tmp_path,[('14b',dict(status=s)) for s in statuses])


@pytest.mark.parametrize('result',[
    dict(status='model_identity_mismatch'),dict(status='model_mismatch'),
    dict(status='http_rejected',turns=[dict(response=dict(http_status=401))]),
    dict(status='http_rejected',turns=[dict(response=dict(http_status=429))])])
def test_identity_authentication_and_rate_rejection_are_immediate_stops(tmp_path,result):
    with pytest.raises(RuntimeError,match=ORIGINAL_SIGNAL):execute(tmp_path,[('14b',result)])


def test_old_failures_age_out_and_transient_http_is_recorded(tmp_path):
    error=dict(status='http_rejected',turns=[dict(response=dict(http_status=502))])
    rows=[('14b',error)]+[('14b',dict(status='answered'))]*32+[('14b',error)]
    assert len(execute(tmp_path,rows)[0])==34


def test_arbitrary_observer_exception_is_never_suppressed(tmp_path):
    def scheduler(items,worker,observe,**kwargs):observe(items[0],worker(items[0]))
    def observe(*args):raise RuntimeError('Integrity check failed')
    with pytest.raises(RuntimeError,match='Integrity check failed'):
        wrap_scheduler(scheduler,tmp_path/'log.jsonl','a'*64)([{}],lambda _:dict(status='transport_error'),observe,model_of=lambda _:'14b')
