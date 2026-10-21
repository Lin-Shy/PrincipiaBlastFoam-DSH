"""Safety boundaries of proposed partial-credit end-to-end aggregation."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments/retrieval_method'))
from chapter2_metric_revision_200 import graded_validity,valid_at_threshold


def answer(**changes):
    return dict(coverage_lower=5/6,coverage_upper=5/6,factuality='pass',
        conditional=True,condition_lower=1,condition_upper=1,**changes)


def test_valid_partial_answer_keeps_credit_but_fails_strict_completion():
    row=answer()
    assert graded_validity(row)==(5/6,5/6)
    assert valid_at_threshold(row,.75)==(1,1)
    assert valid_at_threshold(row,1)==(0,0)


def test_wrong_scenario_cannot_gain_partial_credit():
    row=answer();row.update(condition_lower=0,condition_upper=0)
    assert graded_validity(row)==(0,0)
    assert valid_at_threshold(row,.75)==(0,0)


def test_established_falsehood_cannot_become_valid_through_high_coverage():
    row=answer();row.update(coverage_lower=1,coverage_upper=1,factuality='fail')
    assert graded_validity(row)==(0,0)
    assert valid_at_threshold(row,.75)==(0,0)


def test_unknown_truth_retains_an_interval_instead_of_being_accepted():
    row=answer();row['factuality']='unknown'
    assert graded_validity(row)==(0,5/6)
    assert valid_at_threshold(row,.75)==(0,1)


def test_nonconditional_question_has_no_invented_condition_penalty():
    row=answer();row.update(conditional=False,condition_lower=0,condition_upper=0)
    assert graded_validity(row)==(5/6,5/6)
