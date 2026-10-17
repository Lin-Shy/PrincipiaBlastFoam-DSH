"""Full frozen v7 path using physical SSE receipts, not semantic output repair."""
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
import hashlib,json,sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments/retrieval_method'))
from chapter2_sse_scoring_view import logical_view,LogicalScoringClient
from chapter2_sse_record_transport import wire
from chapter2_score_knowledge_formal import score_answer
from chapter2_v2_development_runner import DeploymentResponse
from test_chapter2_reasoning_answer_scoring import sample

class PhysicalClient:
    def __init__(self,folder,values):
        self.folder=folder;self.values=values;self.deployment=SimpleNamespace(model='qwen3-14b');self.records=[]
    def __call__(self,body,turn):
        self.folder.mkdir(exist_ok=True);raw=self.folder/f'{turn:02d}.sse';raw.write_bytes(b'synthetic SSE fixture')
        response=dict(model='qwen3-14b',usage=dict(completion_tokens=200),choices=[dict(finish_reason='stop',message=dict(content=json.dumps(self.values[turn])))])
        actual={**deepcopy(body),'stream':True,'stream_options':{'include_usage':True}}
        digest=lambda value:hashlib.sha256(wire(value)).hexdigest()
        record=dict(status='response',request=actual,logical_request=deepcopy(body),request_sha256=digest(actual),logical_request_sha256=digest(body),response=response,raw_response=deepcopy(response),canonical_response_sha256=digest(response),raw_sse_file=raw.name,raw_response_sha256=hashlib.sha256(raw.read_bytes()).hexdigest(),sse_done=True,seconds=.01)
        (self.folder/f'{turn:02d}.json').write_text(json.dumps(record),encoding='utf-8');self.records.append(deepcopy(record));return record

def test_actual_full_v7_chain_retains_omission_and_preserves_physical_evidence(tmp_path):
    payload,values,_=sample();physical=PhysicalClient(tmp_path,values)
    result=score_answer(dict(status='answered'),payload,DeploymentResponse(LogicalScoringClient(physical),'qwen3-14b'),lambda _:100)
    assert result['status']=='judged' and result['metrics']['complete_valid_answer']==0
    assert result['metrics']['required_point_coverage_lower']==.5
    assert len(physical.records)==3
    for turn,record in enumerate(physical.records):
        assert record==json.loads((tmp_path/f'{turn:02d}.json').read_text()) and record['request']['stream'] is True
        assert 'SOURCE_SECRET' not in record['logical_request']['messages'][1]['content'] if turn<2 else 'SOURCE_SECRET' in record['logical_request']['messages'][1]['content']

def test_unadapted_physical_chain_reproduces_original_binding_failure(tmp_path):
    payload,values,_=sample();physical=PhysicalClient(tmp_path,values)
    result=score_answer(dict(status='answered'),payload,DeploymentResponse(physical,'qwen3-14b'),lambda _:100)
    assert result['status']=='judge_unknown' and result['reason']=='reasoning_judge_request_binding_mismatch'

@pytest.mark.parametrize('damage',['logical','wire','wire_hash','logical_hash','physical','raw','canonical','done'])
def test_corrupt_transport_cannot_be_admitted_by_logical_view(tmp_path,damage):
    body=dict(model='qwen3-14b',messages=[dict(role='user',content='synthetic')],stream=False);c=PhysicalClient(tmp_path,[{}]);record=c(body,0)
    if damage=='logical':record['logical_request']['messages'][0]['content']='changed'
    elif damage=='wire':record['request']['temperature']=1
    elif damage=='wire_hash':record['request_sha256']='0'*64
    elif damage=='logical_hash':record['logical_request_sha256']='0'*64
    elif damage=='physical':pass
    elif damage=='raw':(tmp_path/'00.sse').write_bytes(b'changed')
    elif damage=='canonical':record['response']['choices'][0]['message']['content']='changed'
    elif damage=='done':record['sse_done']=False
    if damage!='physical':(tmp_path/'00.json').write_text(json.dumps(record),encoding='utf-8')
    else:record['seconds']=2
    with pytest.raises(ValueError):logical_view(record,body,tmp_path,0)

def test_transport_failure_stays_failure_without_response_repair(tmp_path):
    body=dict(model='qwen3-14b',messages=[],stream=False);c=PhysicalClient(tmp_path,[{}]);record=c(body,0);record['status']='transport_error';record['sse_done']=False
    (tmp_path/'00.json').write_text(json.dumps(record),encoding='utf-8')
    assert logical_view(record,body,tmp_path,0)['status']=='transport_error'
