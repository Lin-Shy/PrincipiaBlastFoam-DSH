from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments/retrieval_method'))
from chapter2_qa_statistics import aggregate_planned,paired_comparison,holm_planned,exact_signflip

def test_missing_repeat_stays_unknown_and_large_group_does_not_dominate_macro():
    ids=['Q1','Q2','Q3'];annotations={q:{'split_group':'large' if q!='Q3' else 'small'} for q in ids}
    scores=[{'question_id':q,'replicate':r,'lower':int(q=='Q3'),'upper':int(q=='Q3')} for q in ids for r in range(2) if (q,r)!=('Q1',1)]
    a=aggregate_planned(scores,annotations,ids,2)
    assert a['planned_observations']==6 and a['missing_observations']==1 and a['independent_groups']==2
    assert a['question_bounds']['Q1']==(0,.5)
    assert a['group_macro_bounds']==(.5,.625) and a['question_micro_bounds'][0]==pytest.approx(1/3)

def test_duplicate_or_unplanned_scores_cannot_change_the_denominator():
    row={'question_id':'Q1','replicate':0,'lower':0,'upper':1}
    with pytest.raises(ValueError,match='duplicate'):aggregate_planned([row,row],{'Q1':{'split_group':'g'}},['Q1'],1)
    with pytest.raises(ValueError,match='unplanned'):aggregate_planned([row],{'Q2':{'split_group':'g'}},['Q2'],1)

def test_unknown_pair_has_bounds_but_no_confirmatory_p_value():
    ann={'Q1':{'split_group':'g'}}
    left=aggregate_planned([{'question_id':'Q1','replicate':0,'lower':0,'upper':1}],ann,['Q1'],1)
    right=aggregate_planned([{'question_id':'Q1','replicate':0,'lower':0,'upper':0}],ann,['Q1'],1)
    c=paired_comparison(left,right,resamples=30)
    assert c['bounds']['difference_bounds']==[0,1] and c['test']['p_one_sided'] is None and not c['significance_claim_allowed']

def test_exact_sign_flips_use_groups_and_keep_zero_groups():
    assert exact_signflip([1,1,1,0])['p_one_sided']==.125
    assert exact_signflip([0,0])['p_one_sided']==1

def test_holm_retains_unknown_hypotheses_in_planned_family():
    comps={'A':{'test':{'p_one_sided':.02},'significance_claim_allowed':True},
      'B':{'test':{'p_one_sided':None},'significance_claim_allowed':False},
      'C':{'test':{'p_one_sided':.2},'significance_claim_allowed':True}}
    rows=holm_planned(comps)
    assert rows['A']['holm_adjusted_p']==.06 and not rows['A']['reject']
    assert rows['B']['planned_family_size']==3 and rows['B']['holm_adjusted_p'] is None
