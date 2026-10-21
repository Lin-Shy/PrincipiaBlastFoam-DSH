import copy
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments/retrieval_method'))
from chapter2_answer_scoring import parse_judgment,JUDGE_MODEL

def sample():
    payload={'answer':'fieldValue is high; delta is zero.','rubric':{'condition_discrimination':True,
      'required_points':[{'id':'K1','weight':1},{'id':'K2','weight':1}],'critical_errors':[{'id':'C1'}]},
      'original_material':{'source':{}}}
    judgment={'points':[{'id':'K1','verdict':'satisfied','answer_quote':'fieldValue is high','evidence_ids':['source'],'reason':'source defines amplitude'},
      {'id':'K2','verdict':'satisfied','answer_quote':'delta is zero','evidence_ids':['source'],'reason':'equal neighboring values'}],
      'critical_errors':[{'id':'C1','triggered':False,'answer_quote':'','reason':'no false assertion'}],
      'additional_claims':[],'factuality':{'verdict':'pass','reason':'matches sources'},
      'applicability':{'verdict':'pass','reason':'uses the equal-pressure condition'}}
    def response(value):return {'status':'response','response':{'model':JUDGE_MODEL,'usage':{'completion_tokens':300},
      'choices':[{'finish_reason':'stop','message':{'content':json.dumps(value)}}]}}
    return payload,judgment,response

def test_full_partial_and_unknown_coverage_are_not_collapsed():
    p,j,r=sample();assert parse_judgment(r(j),p)['metrics']['complete_valid_answer']==1
    j['points'][1].update(verdict='partial');m=parse_judgment(r(j),p)['metrics']
    assert m['complete_valid_answer']==0 and m['required_point_coverage_lower']==.75
    j['points'][1].update(verdict='unknown',answer_quote='');m=parse_judgment(r(j),p)['metrics']
    assert m['complete_valid_answer'] is None and m['required_point_coverage_lower']==.5 and m['required_point_coverage_upper']==1

def test_known_omission_stays_failure_even_with_a_separate_unknown():
    p,j,r=sample();j['points'][0].update(verdict='omitted',answer_quote='');j['points'][1].update(verdict='unknown',answer_quote='')
    m=parse_judgment(r(j),p)['metrics'];assert m['complete_lower']==m['complete_upper']==0

def test_skipped_ids_false_claim_pass_and_fabricated_quotes_are_unknown():
    p,j,r=sample();j['points'].pop();assert parse_judgment(r(j),p)['status']=='judge_unknown'
    p,j,r=sample();j['points'][1]['verdict']='contradicted';assert parse_judgment(r(j),p)['reason']=='judge_false_claim_and_factuality_contradiction'
    p,j,r=sample();j['points'][1]['answer_quote']='delta is large';assert parse_judgment(r(j),p)['reason']=='judge_quote_not_in_answer'

def test_nonconditional_and_generation_transport_status_have_distinct_meanings():
    p,j,r=sample();p['rubric']['condition_discrimination']=False;j['applicability']['verdict']='not_applicable'
    assert parse_judgment(r(j),p)['metrics']['complete_valid_answer']==1
    assert parse_judgment({'status':'transport_error'},p)=={'status':'judge_unknown','reason':'transport_error'}

def test_missing_judge_usage_or_wrong_model_cannot_count_as_valid_score():
    p,j,r=sample();response=r(j);response['response']['usage']={}
    assert parse_judgment(response,p)['status']=='judge_unknown'
    response=r(j);response['response']['model']='different-model'
    assert parse_judgment(response,p)['reason']=='judge_model_mismatch'
