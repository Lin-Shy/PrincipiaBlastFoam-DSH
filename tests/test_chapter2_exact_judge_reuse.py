from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments/retrieval_method'))
from chapter2_exact_judge_reuse import ExactJudgeReuse,request_sha
from chapter2_qwen_local import LocalModel
from chapter2_v2_retrieval_probe import save


class Client:
    deployment=LocalModel('https://example.com/v1/chat/completions','qwen3-14b','test')
    def __init__(self):self.calls=[]
    def __call__(self,body,turn):self.calls.append((body,turn));return dict(status='response')


def old(tmp_path,body,status='response'):
    save(tmp_path/'old/00.json',dict(endpoint=Client.deployment.endpoint,model='qwen3-14b',
        request=body,request_sha256=request_sha(body),status=status))


def test_identical_request_reuses_receipt_without_another_physical_call(tmp_path):
    body=dict(model='qwen3-14b',messages=[{'content':'same actual answer and hypothesis'}]);old(tmp_path,body)
    client=Client();reuse=ExactJudgeReuse(client,tmp_path/'old',tmp_path/'references')
    assert reuse(body,4)['exact_request_reused'] is True
    assert not client.calls and reuse.reused==1 and (tmp_path/'references/04.json').exists()


def test_changed_hypothesis_is_a_new_recorded_request_not_a_reused_verdict(tmp_path):
    old(tmp_path,{'hypothesis':'meaning and default'})
    client=Client();reuse=ExactJudgeReuse(client,tmp_path/'old',tmp_path/'references')
    reuse({'hypothesis':'default only'},0)
    assert len(client.calls)==1 and reuse.fresh==1 and reuse.reused==0


@pytest.mark.parametrize('status',['http_rejected','transport_error','invalid_response'])
def test_old_failure_is_preserved_without_replay_or_new_circuit(status,tmp_path):
    body={'hypothesis':'same'};old(tmp_path,body,status)
    client=Client();reuse=ExactJudgeReuse(client,tmp_path/'old',tmp_path/'references')
    assert reuse(body,0)['status']==status
    assert not client.calls and reuse.new_transport_failed is False


def test_unresolved_old_attempt_is_never_reissued(tmp_path):
    body={'hypothesis':'same'};old(tmp_path,body,'in_flight')
    client=Client();reuse=ExactJudgeReuse(client,tmp_path/'old',tmp_path/'references')
    with pytest.raises(ValueError,match='Unresolved'):reuse(body,0)
    assert not client.calls
