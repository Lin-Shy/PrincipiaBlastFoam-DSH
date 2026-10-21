"""Hand-computable continuous-outcome checks for the revised score inference."""
import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments/retrieval_method'))
from chapter2_revision_analysis_200 import effect_intervals


def test_continuous_constant_effect_has_exact_four_group_sign_tail():
    result=effect_intervals([[.6,.6]]*4,[[.2,.2]]*4,list('abcd'),replicates=500)
    assert result['difference_lower']==pytest.approx(.4)
    assert result['uncertainty_envelope_ci95']==pytest.approx([.4,.4])
    assert result['exact_cluster_sign_randomization_p_upper']==.125


def test_unknown_bounds_crossing_zero_do_not_establish_positive_effect():
    result=effect_intervals([[.2,.8],[.8,.8]],[[.6,.6]]*2,['a','b'],replicates=500)
    assert result['difference_lower']==pytest.approx(-.1)
    assert result['difference_upper']==pytest.approx(.2)
    assert result['exact_cluster_sign_randomization_p_upper']==1


def test_macro_and_micro_keep_preexisting_group_weights_separate():
    result=effect_intervals([[x,x] for x in [.8,.1,.1,.1]],[[0,0]]*4,['a','b','b','b'],replicates=500)
    assert result['difference_lower']==pytest.approx(.275)
    assert result['macro_difference_lower']==pytest.approx(.45)
