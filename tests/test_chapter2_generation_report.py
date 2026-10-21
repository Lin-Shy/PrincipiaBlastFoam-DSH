"""The independent audit retains failed citations and rejects request replay."""
import hashlib
import json
from pathlib import Path
import sys
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments/retrieval_method'))
from chapter2_publication_generation_report import audit_session
from chapter2_qa_deployment import prepared_messages, ANSWER_CHECKLIST
from chapter2_common_qa_interface import neutral_messages


def fixture(tmp_path,*,bad_citation=False):
    def save(path,value):
        path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(value),encoding='utf-8')
    protocol=dict(knowledge_budget=dict(tool_calls=8,tool_characters=6000,total_characters=24000),
        model_budget=dict(input_tokens_total=196608,output_tokens_total=16384,input_tokens_per_request=32768,output_tokens_per_request=2048))
    save(tmp_path/'protocol.json',protocol)
    endpoint='https://example.test/v1/chat/completions';save(tmp_path/'user-authorization.json',dict(endpoint=endpoint))
    body=dict(model='qwen3-8b',max_tokens=100,messages=[dict(role='system',content='Prompt\n可用工具：[]'),dict(role='user',content='Natural question')])
    actual={**body,'messages':neutral_messages(prepared_messages(body['messages'],ANSWER_CHECKLIST))}
    record=dict(request=actual,request_sha256=hashlib.sha256(json.dumps(actual,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
        provider='qwen_proxy',model='qwen3-8b',endpoint=endpoint,transport_attempts=1,content_retries=0,status='response',
        raw_response=dict(model='qwen3-8b',usage=dict(prompt_tokens=20,completion_tokens=10,total_tokens=30)),
        started_utc='2026-10-19T00:00:00+00:00',seconds=.1)
    folder=tmp_path/'generation/none/Q1'
    save(folder/'requests/00.json',record)
    refs=[dict(path='manual/not_read.md',start=1,end=1)] if bad_citation else []
    save(folder/'result.json',dict(id='Q1',arm='none',protocol_sha256=hashlib.sha256((tmp_path/'protocol.json').read_bytes()).hexdigest(),
        status='answered',counted_input_tokens=20,actual_completion_tokens=10,knowledge_characters=0,
        tool_events=[],delivered_lines=[],turns=[dict(request=body,counted_input_tokens=20)],
        answer='Actual answer',references=refs,references_delivered=not bad_citation))
    return protocol,folder,record


def test_bad_citation_is_reported_without_rewriting_a_delivered_answer(tmp_path):
    protocol,folder,_=fixture(tmp_path,bad_citation=True)
    before=(folder/'result.json').read_bytes()
    result=audit_session(tmp_path,'none','Q1','Natural question',protocol,{})
    assert result['status']=='answered' and result['references_delivered'] is False
    assert (folder/'result.json').read_bytes()==before


def test_multiple_transport_attempts_are_an_audit_failure(tmp_path):
    protocol,folder,record=fixture(tmp_path)
    record['transport_attempts']=2
    (folder/'requests/00.json').write_text(json.dumps(record),encoding='utf-8')
    with pytest.raises(ValueError,match='replayed'):audit_session(tmp_path,'none','Q1','Natural question',protocol,{})
