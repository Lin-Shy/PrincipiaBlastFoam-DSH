import sys
from pathlib import Path
from fractions import Fraction
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments/retrieval_method'))
import leaderboard_audit as audit
from leaderboard_comparison import compatible,exact_success
from leaderboard_comparison import write_report


def fixture(root,question='same'):
    audit.save(root/'protocol.json',{'files':{},'corpus_id':'corpus','model':'model','replicates':3})
    audit.save(root/'control/questions.json',[question])
    audit.save(root/'control/evaluation_only/annotations.json',[])
    audit.save(root/'control/evaluation_only/scoring-rules.json',{})
    return {'protocol_sha256':audit.sha(root/'protocol.json'),'all_arms_rankable':True,'provider_fingerprints':{'one':3}}


def test_different_questions_or_incomplete_review_cannot_enter_shared_board(tmp_path):
    a=tmp_path/'a';b=tmp_path/'b';ra=fixture(a);rb=fixture(b,'changed')
    with pytest.raises(ValueError,match='questions.json'):compatible([a,b],[ra,rb])
    rb=fixture(b);rb['all_arms_rankable']=False
    with pytest.raises(ValueError,match='incomplete'):compatible([a,b],[ra,rb])


def test_category_macro_ties_are_exact_not_float_order_artifacts():
    rows=[{'category':cat,'quality':{'qa_success':success}} for cat,values in [('a',[True,True,False]),('b',[True,False,False]),('c',[True,False,False])] for success in values]
    assert exact_success({'sessions':rows})==Fraction(4,9)


def test_report_discloses_terminal_failures_and_submetric_applicability(tmp_path):
    metric={'macro_over_applicable_categories':.5,'by_category':{'cross':{'mean':.5}}}
    row={'rank':1,'arm':'full_candidate','method':'retrieval_first','exact_success_fraction':'1/2',
         'strict_success_95ci':[.25,.75],'states':{'reviewed':54,'tested_terminal_failure':54},
         'metrics':{'answer_accuracy':metric,'citation_accuracy':metric,'cross_source_completeness':metric}}
    write_report({'arms':[row],'paired_comparisons':[]},tmp_path/'r.md')
    text=(tmp_path/'r.md').read_text()
    assert '54答案/54运行失败' in text and '只在实际生成并完成来源评审的答案上适用' in text
