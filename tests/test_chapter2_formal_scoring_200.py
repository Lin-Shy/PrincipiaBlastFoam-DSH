import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments/retrieval_method'))
from chapter2_formal_scoring_200 import failed_generation, unidentified
from chapter2_judge_200 import call_once


def test_generation_failure_is_zero_without_semantic_judgment():
    result=failed_generation('completion_truncated')
    assert result['reason']=='completion_truncated'
    assert result['metrics']['complete_lower']==result['metrics']['complete_upper']==0
    assert result['metrics']['required_point_coverage_upper']==0
    assert result['metrics']['factuality']=='not_evaluated'


def test_unknown_remains_full_denominator_interval():
    result=unidentified('judge_input_budget_exceeded_before_export')
    assert result['metrics']['complete_valid_answer'] is None
    assert result['metrics']['complete_lower']==0
    assert result['metrics']['complete_upper']==1


def test_resume_never_reissues_unresolved_or_changed_request(tmp_path):
    import json
    import pytest
    class NeverCall:
        folder=tmp_path
        def __call__(self,*args):raise AssertionError('Must not resend')
    path=tmp_path/'00.json'
    path.write_text(json.dumps(dict(status='in_flight',request={'model':'qwen3-14b'})))
    with pytest.raises(ValueError):call_once(NeverCall(),{'model':'qwen3-14b'},0)
    path.write_text(json.dumps(dict(status='response',request={'model':'qwen3-14b'})))
    with pytest.raises(ValueError):call_once(NeverCall(),{'model':'different'},0)
    assert call_once(NeverCall(),{'model':'qwen3-14b'},0)['status']=='response'
