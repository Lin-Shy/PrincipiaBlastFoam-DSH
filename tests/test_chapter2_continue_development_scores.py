from datetime import datetime,timezone,timedelta
from pathlib import Path
import sys
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments/retrieval_method'))
from chapter2_continue_development_scores import partition,verify_availability
from chapter2_v2_retrieval_probe import save,sha
from chapter2_exact_judge_reuse import request_sha


def test_partition_keeps_old_failed_verdict_and_only_admits_unattempted_questions(tmp_path):
    generation=tmp_path/'generation';source=tmp_path/'scores'
    protocol=dict(models=['qwen3-8b'],methods=['graph'],question_ids=['A','B'])
    for qid in protocol['question_ids']:save(generation/f'sessions/qwen3-8b/graph/{qid}/result.json',dict(question=qid))
    old=source/'sessions/qwen3-8b/graph/A/score.json'
    save(old,dict(model='qwen3-8b',method='graph',id='A',status='judge_unknown',reason='transport_error',
        result_sha256=sha(generation/'sessions/qwen3-8b/graph/A/result.json')))
    jobs,existing=partition(generation,source,protocol)
    assert [r['id'] for r in jobs]==['B'] and existing[0][-1]['reason']=='transport_error'
    save(source/'sessions/qwen3-8b/graph/B/requests/00.json',dict(status='in_flight'))
    with pytest.raises(ValueError,match='Orphan'):partition(generation,source,protocol)


def test_availability_requires_fresh_exact_model_and_unchanged_actual_request(tmp_path):
    now=datetime(2026,10,17,tzinfo=timezone.utc);body=dict(model='qwen3-14b',messages=[])
    row=dict(provider='qwen_proxy',status='response',model='qwen3-14b',started_utc=now.isoformat(),
        endpoint='https://example.invalid/v1/chat/completions',request=body,request_sha256=request_sha(body),raw_response=dict(model='qwen3-14b'))
    path=tmp_path/'receipt.json';save(path,row)
    assert verify_availability(path,now=now)==row['endpoint']
    with pytest.raises(ValueError,match='Fresh'):verify_availability(path,now=now+timedelta(seconds=601))
