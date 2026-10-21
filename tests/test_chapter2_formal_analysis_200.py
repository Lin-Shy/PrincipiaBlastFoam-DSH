import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments/retrieval_method'))
from chapter2_formal_analysis_200 import holm,effect_intervals,duplicate_input_stability


def test_holm_preserves_original_order_and_monotonicity():
    assert holm([.04,.01,.03])==pytest.approx([.06,.03,.06])


def test_cluster_randomization_exact_known_outcomes():
    r=effect_intervals([[1,1]]*4,[[0,0]]*4,['a','a','b','b'],replicates=100)
    assert r['difference_lower']==r['difference_upper']==1
    assert r['exact_cluster_sign_randomization_p_upper']==.5
    assert r['uncertainty_envelope_ci95']==[1,1]


def test_unknown_difference_cannot_force_positive_effect():
    r=effect_intervals([[0,1]]*4,[[0,1]]*4,['a','a','b','b'],replicates=100)
    assert r['difference_lower']==-1 and r['difference_upper']==1
    assert r['exact_cluster_sign_randomization_p_upper']==1


def test_knowledge_group_macro_does_not_duplicate_large_groups():
    r=effect_intervals([[1,1]]*3+[[0,0]],[[0,0]]*4,['a']*3+['b'],replicates=100)
    assert r['difference_lower']==.75
    assert r['macro_difference_lower']==.5


def test_identical_input_judge_disagreement_is_reported_not_reconciled():
    left=dict(judge_payload_sha256='same',cv_lower=0,cv_upper=0,coverage_lower=.5,coverage_upper=.5,
        condition_lower=0,condition_upper=0,factuality='pass',applicability='not_applicable')
    right={**left,'cv_lower':1,'cv_upper':1,'coverage_lower':1,'coverage_upper':1}
    result=duplicate_input_stability([left,right,{**left,'judge_payload_sha256':'different'}])
    assert result['repeated_packet_groups']==1 and result['all_pairs']==1
    assert result['determinate_complete_discordant_pairs']==1
    assert left['cv_upper']==0 and right['cv_lower']==1
