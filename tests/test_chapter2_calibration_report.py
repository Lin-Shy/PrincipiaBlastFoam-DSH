from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments/retrieval_method'))
from chapter2_report_score_calibration import summarize

def expected():
    return {'controls':[{'control_id':'Q_positive','question_id':'Q','type':'positive','expected_complete':1},
      {'control_id':'Q_omission','question_id':'Q','type':'omission','expected_complete':0}],
      'acceptance_before_scoring':{'min_controls':2,'min_questions':1,'minimum_parse_rate':.9,
       'minimum_all_control_complete_agreement':.9,'minimum_per_class_agreement':.8}}

def test_invalid_inputs_do_not_replace_missing_valid_judgments_or_shrink_denominator():
    obs=[{'control_id':'Q_positive','candidate_matches_expected':True,'status':'judged','complete':1},
      {'control_id':'Q_omission','candidate_matches_expected':False,'status':'judged','complete':0}]
    r=summarize(expected(),obs)
    assert r['overall']['controls']==2 and r['overall']['complete_agreement_lower']==.5
    assert r['overall']['complete_agreement_upper']==1 and len(r['invalid_input_observations'])==1
    assert not r['numeric_thresholds_passed'] and not r['ready_for_formal_judge_freeze']

def test_duplicate_valid_candidates_rejected_and_numeric_success_needs_semantic_review():
    obs=[{'control_id':'Q_positive','candidate_matches_expected':True,'status':'judged','complete':1},
      {'control_id':'Q_omission','candidate_matches_expected':True,'status':'judged','complete':0}]
    assert summarize(expected(),obs)['numeric_thresholds_passed']
    assert not summarize(expected(),obs)['ready_for_formal_judge_freeze']
    with pytest.raises(ValueError,match='scored twice'):summarize(expected(),obs+[obs[0]])
