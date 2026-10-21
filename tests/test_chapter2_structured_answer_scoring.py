import copy
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments/retrieval_method'))
from chapter2_structured_answer_scoring import structured_payload,parse_structured_judgment
from chapter2_answer_scoring import JUDGE_MODEL

def sample():
    p={'question':'Does either threshold suffice?','answer':'Either threshold suffices.','rubric':{
      'condition_discrimination':True,'applicability':'OR rule','acceptable_answer_range':'equivalent wording',
      'required_points':[{'id':'Q.K1','weight':1,'claim':'OR rule','evidence_ids':['S']}],
      'critical_errors':[{'id':'C1','claim':'Both thresholds must be reached'}]},'original_material':{'S':{}}}
    j={'points':[{'id':'K1','verdict':'full','answer_segment_ids':['A1'],'source_ids':['S'],'reason':'says either'}],
      'false_assertion_checks':[{'id':'F1','candidate_asserts_false_claim':'no','answer_segment_ids':[],'reason':'does not affirm AND'}],
      'segment_audit':[{'id':'A1','verdict':'source_supported','source_ids':['S'],'reason':'matches OR'}],
      'applicability':{'verdict':'correct','reason':'correct condition conclusion'}}
    def response(v):return {'status':'response','response':{'model':JUDGE_MODEL,'usage':{'completion_tokens':200},
      'choices':[{'finish_reason':'stop','message':{'content':json.dumps(v)}}]}}
    return p,j,response

def test_denial_of_false_assertion_is_not_an_error_and_factuality_is_derived():
    p,j,r=sample();result=parse_structured_judgment(r(j),p)
    assert result['metrics']['complete_valid_answer']==1
    assert result['metrics']['critical_errors_triggered']==0
    j['false_assertion_checks'][0].update(candidate_asserts_false_claim='yes',answer_segment_ids=['A1'])
    result=parse_structured_judgment(r(j),p)
    assert result['metrics']['factuality']=='fail' and result['metrics']['complete_valid_answer']==0

def test_every_segment_checked_and_unknown_false_assertion_bounds_preserved():
    p,j,r=sample();p['answer']+='\nAnother assertion.'
    assert parse_structured_judgment(r(j),p)['reason']=='structured_judge_incomplete_ids'
    p,j,r=sample();j['false_assertion_checks'][0]['candidate_asserts_false_claim']='unknown'
    m=parse_structured_judgment(r(j),p)['metrics']
    assert m['complete_lower']==0 and m['complete_upper']==1 and m['factuality']=='unknown'

def test_wrong_source_and_actual_segment_ids_are_rejected():
    p,j,r=sample();j['points'][0]['answer_segment_ids']=['A999']
    assert parse_structured_judgment(r(j),p)['reason']=='structured_answer_segment_invalid'
    p,j,r=sample();j['segment_audit'][0]['source_ids']=['invented']
    assert parse_structured_judgment(r(j),p)['reason']=='structured_source_id_invalid'

def test_source_insufficient_extra_claim_and_partial_point_do_not_become_success():
    p,j,r=sample();j['segment_audit'][0].update(verdict='source_insufficient',source_ids=[])
    assert parse_structured_judgment(r(j),p)['metrics']['complete_valid_answer'] is None
    j['points'][0]['verdict']='partial'
    assert parse_structured_judgment(r(j),p)['metrics']['complete_valid_answer']==0

def test_point_ids_anonymized_without_changing_original_payload():
    p,_,_=sample();before=copy.deepcopy(p);v,points,errors=structured_payload(p)
    assert p==before and points=={'K1':'Q.K1'} and errors=={'F1':'C1'}
    assert v['candidate_segments'][0]['text']==p['answer']
