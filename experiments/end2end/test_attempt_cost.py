import importlib.util
import json
from pathlib import Path
import sys
import zstandard
import pytest

sys.path.insert(0,str(Path(__file__).parent))
from collect_attempt_cost import collect

def session(root,events):
    root.mkdir(parents=True)
    file=root/'session.v2.jsonl.zstd'
    file.write_bytes(b''.join(zstandard.ZstdCompressor().compress((json.dumps(e)+'\n').encode()) for e in events))
    return file

def test_partial_usage_compaction_and_duplicate_input(tmp_path):
    session(tmp_path/'one',[
        {'type':'assistant/message','data':{'usage':{'totalTokens':10,'cacheReadTokens':3}}},
        {'type':'compaction/summary','data':{'usage':{'totalTokens':4}}},
        {'type':'assistant/message','data':{}},
        {'type':'llm/retry','data':{}},
        {'type':'tool/result','data':{'usage':{'totalTokens':999}}},
    ])
    result=collect([tmp_path,tmp_path/'one'])
    assert result['summary']['sessions']==1
    assert result['summary']['reported_usage_sums']['totalTokens']==14
    assert result['summary']['records_missing_field']['totalTokens']==1
    assert result['summary']['complete_provider_total_tokens'] is None
    assert result['summary']['provider_request_count'] is None
    assert len(result['events'])==4

def test_identical_sessions_not_silently_discarded(tmp_path):
    event=[{'type':'assistant/message','data':{'usage':{'totalTokens':2}}}]
    session(tmp_path/'a',event);session(tmp_path/'b',event)
    assert collect([tmp_path])['summary']['reported_usage_sums']['totalTokens']==4

def test_empty_and_invalid_not_zero_bill(tmp_path):
    assert collect([tmp_path])['summary']['coverage']=='no_sessions_found'
    assert collect([tmp_path])['summary']['actual_model_money'] is None
    session(tmp_path/'bad',[{'type':'assistant/message','data':{'usage':{'totalTokens':-1}}}])
    with pytest.raises(ValueError):collect([tmp_path])
