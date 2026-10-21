import copy
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments/retrieval_method'))
from chapter2_staged_answer_scoring import staged_requests,parse_staged_judgments,JUDGE_MODEL

def sample(conditional=False):
    p={'question':'Explain rule','answer':'Correct rule.','rubric':{
      'required_points':[{'id':'Q.K1','weight':1,'claim':'Correct rule','evidence_ids':['S']}],
      'critical_errors':[{'id':'C1','claim':'Incorrect rule'}],'condition_discrimination':conditional,
      'applicability':'Under given condition','acceptable_answer_range':'Equivalent explanation'},'original_material':{'S':{}}}
    point={'verdict':'full','answer_segment_ids':['A1'],'source_ids':['S'],'reason':'candidate states rule'}
    audit={'segments':[{'id':'A1','verdict':'supported','source_ids':['S'],'reason':'matches original'}]}
    if conditional:audit['applicability']={'verdict':'correct','reason':'correct conclusion'}
    def responses(values):
        return [{'status':'response','request':r['body'],'response':{'model':JUDGE_MODEL,'usage':{'completion_tokens':100},
          'choices':[{'finish_reason':'stop','message':{'content':json.dumps(v)}}]}} for r,v in zip(staged_requests(p),values)]
    return p,point,audit,responses

def test_isolated_point_and_source_audit_have_separate_reference_inputs():
    p,point,audit,r=sample();requests=staged_requests(p)
    assert len(requests)==2 and 'evaluation_claim' in requests[0]['body']['messages'][1]['content']
    payload=json.loads(requests[1]['body']['messages'][1]['content'])
    assert 'rubric' not in payload and 'evaluation_claim' not in payload and 'applicability_task' not in payload
    m=parse_staged_judgments(r([point,audit]),p)['metrics']
    assert m['complete_valid_answer']==1 and m['applicability']=='not_applicable' and 'critical_errors_triggered' not in m

def test_partial_and_missing_points_fail_without_being_factual_contradictions():
    p,point,audit,r=sample();point['verdict']='partial'
    m=parse_staged_judgments(r([point,audit]),p)['metrics'];assert m['complete_valid_answer']==0 and m['factuality']=='pass'
    point.update(verdict='missing',answer_segment_ids=[],source_ids=[])
    assert parse_staged_judgments(r([point,audit]),p)['metrics']['complete_valid_answer']==0

def test_source_unknown_and_condition_fail_have_distinct_bounds():
    p,point,audit,r=sample(True);audit['segments'][0].update(verdict='unknown',source_ids=[])
    assert parse_staged_judgments(r([point,audit]),p)['metrics']['complete_valid_answer'] is None
    audit['applicability']['verdict']='incorrect'
    m=parse_staged_judgments(r([point,audit]),p)['metrics'];assert m['complete_lower']==m['complete_upper']==0

def test_request_binding_truncation_missing_stages_and_invented_ids_rejected():
    p,point,audit,r=sample();response=r([point,audit]);response[0]['request']['max_tokens']=999
    assert parse_staged_judgments(response,p)['reason']=='staged_judge_request_binding_mismatch'
    response=r([point,audit]);response[0]['response']['choices'][0]['finish_reason']='length'
    assert parse_staged_judgments(response,p)['reason']=='judge_completion_truncated'
    assert parse_staged_judgments(r([point]),p)['reason']=='staged_judge_missing_response'
    point['answer_segment_ids']=['invented']
    assert parse_staged_judgments(r([point,audit]),p)['reason']=='staged_judge_invalid_ids'

def test_contradiction_in_source_audit_overrides_full_point_coverage():
    p,point,audit,r=sample();audit['segments'][0]['verdict']='contradicted'
    m=parse_staged_judgments(r([point,audit]),p)['metrics']
    assert m['required_point_coverage_lower']==1 and m['complete_valid_answer']==0 and m['factuality']=='fail'
