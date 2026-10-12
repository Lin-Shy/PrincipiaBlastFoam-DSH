import importlib.util
import json
from pathlib import Path
import zstandard

spec=importlib.util.spec_from_file_location('native_audit',Path(__file__).resolve().parents[1]/'experiments/retrieval_method/audit_native_session.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


def test_reads_concatenated_zstd_frames_and_does_not_double_count_tokens(tmp_path):
    events=[{'type':'session'},
            {'type':'tool/call','data':{'name':'skill','arguments':'{"name":"knowledge"}'}},
            {'type':'assistant/message','data':{'usage':{'inputTokens':2,'cacheReadTokens':3,'outputTokens':4,'reasoningTokens':1,'totalTokens':9}}},
            {'type':'turn/end','data':{'reason':{'kind':'completed'}}}]
    p=tmp_path/'session.zstd';compressor=zstandard.ZstdCompressor()
    p.write_bytes(b''.join(compressor.compress((json.dumps(e)+'\n').encode()) for e in events))
    result=module.audit(module.read_events(p))
    assert result['events']==4 and result['tool_calls']==1
    assert result['loaded_skills']==['knowledge']
    assert result['reported_usage']['totalTokens']==9
    assert result['turn_end']==[{'kind':'completed'}]


def test_tool_text_counts_model_visible_text_once_including_errors():
    events=[{'type':'tool/call','data':{'callId':'a','name':'lookup','arguments':'{}'}},
            {'type':'tool/result','data':{'message':{'content':[{'type':'tool-result','toolCallId':'a','content':[{'type':'text','text':'空气模型'},{'type':'image','data':'ignored'}],'structuredContent':{'duplicate':'空气模型'}}]}}},
            {'type':'tool/result','data':{'message':{'content':[{'type':'tool-result','toolCallId':'missing','isError':True,'content':[{'type':'text','text':'error'}]}]}}}]
    result=module.audit(events)
    assert result['all_tool_text_characters']==9
    assert result['tool_text_characters']=={'lookup':4,'unknown':5}
    assert result['tool_errors']==1
def test_session_identity_ignores_other_trials_seen_in_tool_output():
    from experiments.retrieval_method.audit_native_session import has_user_task
    task='Create outputs/trial-one using the selected tutorial.'
    other=[{'type':'user/message','data':{'content':[{'type':'text','text':task.replace('trial-one','trial-two')}]}},
           {'type':'tool/result','data':{'content':[{'type':'text','text':task}]}}]
    assert not has_user_task(other,task)
    assert has_user_task([{'type':'user/message','data':{'content':[{'type':'text','text':task}]}}],task)
