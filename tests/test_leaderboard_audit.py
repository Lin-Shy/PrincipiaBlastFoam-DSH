import sys
import json
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments/retrieval_method'))
import leaderboard_audit as audit


def test_unrun_usage_and_latency_are_unknown(tmp_path):
    value=audit.ledger(tmp_path/'not-run')
    assert value['actual_total_tokens'] is None
    assert value['session_seconds'] is None
    assert value['reported_usage']=={}


def test_failed_attempt_does_not_become_zero_cost(tmp_path):
    (tmp_path/'step-01.json').write_text(json.dumps({'request_sha256':'fixture','events':[{'status':'transport_error','usage':None},
          {'status':'response','usage':{'prompt_tokens':7,'completion_tokens':3,'total_tokens':10}}],
          'raw_response':{'model':'fixture','system_fingerprint':'version-a'}}))
    value=audit.ledger(tmp_path)
    assert value['reported_usage']['total_tokens']==10
    assert value['unknown_usage_attempts']==1
    assert value['actual_total_tokens'] is None
    assert value['provider_fingerprints']=={'version-a':1}


def test_latency_quantiles_do_not_use_missing_as_zero():
    assert audit.percentile([],.95) is None
    assert audit.percentile([10,20],.5)==15
