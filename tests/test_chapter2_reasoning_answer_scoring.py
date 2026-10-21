import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments/retrieval_method'))
from chapter2_reasoning_answer_scoring import reasoning_requests,parse_reasoning_judgments,JUDGE_MODEL

def sample():
    p={'question':'Explain selection and EOS','answer':'Several phases select the multiphase solver.','rubric':{
      'required_points':[{'id':'K1','weight':1,'claim':'Several phases select multiphase'},{'id':'K2','weight':1,'claim':'All phases use blastFoam EOS'}],
      'critical_errors':[],'condition_discrimination':False,'applicability':'No condition'},'original_material':{'S':{'text':'SOURCE_SECRET'}}}
    values=[{'verdict':'full','answer_segment_ids':['A1'],'reason':'states selection'},
      {'verdict':'missing','answer_segment_ids':[],'reason':'no EOS claim in candidate'},
      {'segments':[{'id':'A1','verdict':'supported','reason':'source supports selection'}],
       'condition':{'verdict':'not_applicable','reason':'not required'}}]
    def responses(vals):
        return [{'status':'response','request':req['body'],'response':{'model':JUDGE_MODEL,'usage':{'completion_tokens':4000,
          'completion_tokens_details':{'reasoning_tokens':3000}},'choices':[{'finish_reason':'stop','message':{'content':json.dumps(v)}}]}}
          for req,v in zip(reasoning_requests(p),vals)]
    return p,values,responses

def test_coverage_stage_cannot_read_original_and_missing_eos_does_not_pass():
    p,v,r=sample();requests=reasoning_requests(p)
    for req in requests[:-1]:
        assert 'SOURCE_SECRET' not in req['body']['messages'][1]['content'] and req['body']['enable_thinking']
    assert 'SOURCE_SECRET' in requests[-1]['body']['messages'][1]['content']
    score=parse_reasoning_judgments(r(v),p)
    assert score['metrics']['complete_valid_answer']==0 and score['metrics']['required_point_coverage_lower']==.5
    assert score['reported_reasoning_tokens']==[3000,3000,3000]

def test_unknown_source_bounds_and_wrong_claims_are_retained():
    p,v,r=sample();v[1].update(verdict='full',answer_segment_ids=['A1']);v[2]['segments'][0]['verdict']='unknown'
    assert parse_reasoning_judgments(r(v),p)['metrics']['complete_valid_answer'] is None
    v[2]['segments'][0]['verdict']='contradicted'
    assert parse_reasoning_judgments(r(v),p)['metrics']['complete_valid_answer']==0

def test_fake_segments_or_missing_audit_segments_are_unknown():
    p,v,r=sample();v[0]['answer_segment_ids']=['A999']
    assert parse_reasoning_judgments(r(v),p)['reason']=='reasoning_actual_answer_ids_invalid'
    p,v,r=sample();v[2]['segments']=[]
    assert parse_reasoning_judgments(r(v),p)['reason']=='reasoning_audit_incomplete_actual_segments'

def test_false_condition_dimension_is_fixed_by_sealed_label_and_budget_enforced():
    p,v,r=sample();v[2]['condition']['verdict']='incorrect'
    assert parse_reasoning_judgments(r(v),p)['metrics']['applicability']=='not_applicable'
    response=r(v);response[0]['response']['usage']['completion_tokens']=8193
    assert parse_reasoning_judgments(response,p)['reason']=='judge_usage_unknown_or_budget_violation'
