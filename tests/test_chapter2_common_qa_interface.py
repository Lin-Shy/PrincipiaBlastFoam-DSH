from copy import deepcopy
import json
from pathlib import Path
import sys
from types import SimpleNamespace

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments/retrieval_method'))
from chapter2_common_qa_interface import neutral_messages,NeutralToolClient
from chapter2_qa_deployment import DeploymentResponse,token_counter,ANSWER_CHECKLIST
from principia_core.retrieval.knowledge_agent import SYSTEM
from principia_core.retrieval.knowledge_qa import tool_specs,wire


def messages(method):return [dict(role='system',content=SYSTEM+'\n可用工具：'+wire(tool_specs(method))),dict(role='user',content='natural question')]


def test_all_four_backends_have_identical_first_request_but_none_has_no_tools():
    transformed=[neutral_messages(messages(m)) for m in ('bm25','e5','hybrid','graph')]
    assert all(row==transformed[0] for row in transformed)
    assert neutral_messages(messages('none'))==messages('none')
    specs=json.loads(transformed[0][0]['content'].split('\n可用工具：')[1])
    assert [s['name'] for s in specs]==['catalog','read_source','search']


def test_counter_matches_actual_submitted_messages_without_mutating_agent_history():
    original=messages('graph');before=deepcopy(original);counted=[];submitted=[]
    class Client:
        deployment=SimpleNamespace(model='qwen3-8b')
        def __call__(self,body,turn):submitted.append(body);return dict(status='transport_error')
    token_counter(lambda m:counted.append(neutral_messages(m)),'bulk',ANSWER_CHECKLIST)(original)
    DeploymentResponse(NeutralToolClient(Client()),'qwen3-8b',ANSWER_CHECKLIST)(dict(messages=original),0)
    assert counted[0]==submitted[0]['messages'] and original==before
    assert len(submitted)==1
