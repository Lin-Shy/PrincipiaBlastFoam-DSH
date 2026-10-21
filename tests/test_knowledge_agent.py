import json
from pathlib import Path
import hashlib
import pytest
from principia_core.retrieval.knowledge_agent import AutonomousKnowledgeAgent,ModelBudget
from principia_core.retrieval.knowledge_qa import FrozenKnowledgeCorpus,KnowledgeToolSession,KnowledgeBudget

def make_tools(tmp_path,budget=None):
    raw=b'pressure threshold\ncondition applies\n'
    source=tmp_path/'manual/rule.md';source.parent.mkdir();source.write_bytes(raw)
    manifest=tmp_path/'manifest.json';manifest.write_text(json.dumps({'schema':'independent_blast_knowledge_corpus_v1',
      'files':[{'path':'manual/rule.md','sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'lines':2}]}))
    class Backend:
        def search(self,query,limit):return [{'path':'manual/rule.md','start':1,'end':2}]
    return KnowledgeToolSession('bm25',FrozenKnowledgeCorpus(tmp_path,manifest),Backend(),budget)

class FakeClient:
    def __init__(self,actions,model='qwen3-8b',usage=10,finish='stop'):
        self.actions=iter(actions);self.model=model;self.usage=usage;self.finish=finish;self.requests=[]
    def __call__(self,body,turn):
        self.requests.append(body)
        return {'status':'response','response':{'model':self.model,'usage':{'completion_tokens':self.usage},
            'choices':[{'finish_reason':self.finish,'message':{'content':json.dumps(next(self.actions))}}]}}

def final(refs=None):return {'action':'final','answer':'依据实际条件判断。','references':refs or []}
def tool(query):return {'action':'tool','name':'search','arguments':{'query':query}}
def agent(tools,client,budget=None,counter=lambda m:100):
    return AutonomousKnowledgeAgent('qwen3-8b',tools,client,counter,budget)

def test_model_autonomously_requeries_and_uses_delivered_lines(tmp_path):
    client=FakeClient([tool('pressure'),tool('condition'),final([{'path':'manual/rule.md','start':1,'end':2}])])
    result=agent(make_tools(tmp_path),client).run('适用什么条件？')
    assert result['status']=='answered' and result['references_delivered']
    assert len(result['tool_events'])==2
    assert '工具返回' in client.requests[1]['messages'][-1]['content']
    assert result['knowledge_characters']==sum(e['delivered_characters'] for e in result['tool_events'])

def test_budget_disables_tools_for_final_turn(tmp_path):
    client=FakeClient([tool('pressure'),final()]);result=agent(make_tools(tmp_path,KnowledgeBudget(tool_calls=1)),client).run('判断')
    assert result['status']=='answered' and result['turns'][1]['final_only']

def test_none_arm_cannot_request_tools_or_read_corpus():
    client=FakeClient([tool('pressure')]);result=agent(KnowledgeToolSession('none'),client).run('判断')
    assert result['status']=='invalid_action' and result['tool_events']==[]

def test_format_failure_is_not_retried(tmp_path):
    client=FakeClient([{'answer':'wrong shape'}]);result=agent(make_tools(tmp_path),client).run('判断')
    assert result['status']=='invalid_action' and len(client.requests)==1

def test_unread_reference_is_reported_without_deleting_answer():
    client=FakeClient([final([{'path':'manual/rule.md','start':1,'end':1}])])
    result=agent(KnowledgeToolSession('none'),client).run('判断')
    assert result['status']=='answered' and not result['references_delivered']

def test_input_tokens_checked_before_paid_request():
    client=FakeClient([final()]);result=agent(KnowledgeToolSession('none'),client,counter=lambda m:32769).run('判断')
    assert result['status']=='input_budget_exhausted' and client.requests==[]

def test_exact_model_identity_required():
    client=FakeClient([final()],model='qwen3-14b');result=agent(KnowledgeToolSession('none'),client).run('判断')
    assert result['status']=='model_identity_mismatch'

def test_reserve_forces_final_and_cannot_add_another_tool(tmp_path):
    client=FakeClient([tool('pressure'),final()],usage=10)
    budget=ModelBudget(output_tokens_per_request=10,output_tokens_total=20,final_output_reserve=10)
    result=agent(make_tools(tmp_path),client,budget).run('判断')
    assert result['status']=='answered' and result['turns'][1]['final_only']
    assert result['actual_completion_tokens']==20

def test_provider_truncation_and_overrun_remain_distinct():
    for client,status in [(FakeClient([final()],finish='length'),'completion_truncated'),
                          (FakeClient([final()],usage=2049),'provider_output_budget_violation')]:
        assert agent(KnowledgeToolSession('none'),client).run('判断')['status']==status

def test_malformed_reference_does_not_crash_the_trajectory():
    client=FakeClient([final([{'path':['manual/rule.md'],'start':1,'end':1}])])
    result=agent(KnowledgeToolSession('none'),client).run('判断')
    assert result['status']=='answered' and result['references_delivered'] is False

def test_failed_transport_keeps_logical_prompt_count_without_inventing_usage():
    def failed(body,turn):return {'status':'transport_error','events':[{'usage':None}]}
    result=agent(KnowledgeToolSession('none'),failed).run('判断')
    assert result['status']=='transport_error' and result['counted_input_tokens']==100
    assert result['actual_completion_tokens']==0 and result['turns'][0]['response']['events'][0]['usage'] is None
