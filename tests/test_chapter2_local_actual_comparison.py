from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments/retrieval_method'))
from chapter2_compare_local_actual_audit import compare


def test_unknown_is_not_agreement_or_failure():
    reference=dict(review_id='S001',question_id='Q',complete_valid_answer=0,
                   required_points=[dict(id='K1',verdict='satisfied')])
    result=compare(reference,dict(status='judge_unknown',metrics=dict(complete_valid_answer=None)))
    assert result['complete_comparison']=='unknown'
    assert result['local_complete'] is None
    assert result['point_comparisons'][0]['same_label'] is None
    assert result['needs_source_review'] is True


def test_complete_agreement_does_not_hide_point_disagreement():
    reference=dict(review_id='S001',question_id='Q',complete_valid_answer=0,
                   required_points=[dict(id='K1',verdict='wrong')])
    score=dict(status='judged',metrics=dict(complete_valid_answer=0),
               judgment=dict(points=[dict(id='K1',verdict='missing')]))
    result=compare(reference,score)
    assert result['complete_comparison']=='agrees'
    assert result['point_comparisons'][0]['same_label'] is False
    assert result['needs_source_review'] is True
