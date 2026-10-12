import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments/retrieval_method'))
from ablation_results import analyze,SINGLES,INTERACTIONS


def row(arm,score):
    sessions=[]
    for family in ['a','b']:
        for i in range(6):sessions.append({'family':family,'quality':{'qa_success':i<score}})
    return {'arm':arm,'method':'retrieval_first','sessions':sessions,'states':{'reviewed':12}}


def test_component_effects_and_difference_in_differences_have_registered_orientation():
    reference={'all_arms_rankable':True,'arms':[row('full_candidate',5),row('strong_no_graph',1)]}
    scores={arm:4 for arm in SINGLES.values()};scores.update({v[2]:3 for v in INTERACTIONS.values()})
    ablations={'all_arms_rankable':True,'arms':[row(arm,score) for arm,score in scores.items()]}
    result=analyze(reference,ablations)
    import pytest
    assert result['component_effects_present_minus_removed']['role_scope']['difference']==pytest.approx(1/6)
    # 5/6 - 4/6 - 4/6 + 3/6 = 0
    assert result['interactions']['role_scope × conditional_bilateral']['difference_in_differences']==pytest.approx(0)


def test_incomplete_cohort_is_rejected():
    import pytest
    with pytest.raises(ValueError,match='source reviews'):
        analyze({'all_arms_rankable':False},{'all_arms_rankable':True})
