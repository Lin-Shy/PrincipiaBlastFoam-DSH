from test_chapter2_reasoning_answer_scoring import sample
from chapter2_source_free_answer_scoring import source_free_requests
from chapter2_partial_answer_scoring import parse_partial_judgments

def recorded(p,v,r):
    response=r(v)
    for req,res in zip(source_free_requests(p),response):res['request']=req['body']
    return response

def test_known_omission_survives_later_invalid_condition_dimension():
    p,v,r=sample();p['rubric']['condition_discrimination']=True
    result=parse_partial_judgments(recorded(p,v,r),p)
    assert result['status']=='partially_judged' and result['reason']=='reasoning_condition_required'
    assert result['metrics']['complete_lower']==result['metrics']['complete_upper']==0
    assert result['metrics']['factuality']=='unknown' and result['metrics']['applicability']=='unknown'

def test_no_failure_cannot_be_manufactured_when_all_points_satisfied():
    p,v,r=sample();p['rubric']['condition_discrimination']=True;v[1].update(verdict='full',answer_segment_ids=['A1'])
    assert parse_partial_judgments(recorded(p,v,r),p)['status']=='judge_unknown'

def test_bad_actual_candidate_ids_cannot_be_recovered_as_known_failure():
    p,v,r=sample();p['rubric']['condition_discrimination']=True;v[0]['answer_segment_ids']=['invented']
    result=parse_partial_judgments(recorded(p,v,r),p)
    assert result['status']=='judge_unknown' and result['reason']=='reasoning_actual_answer_ids_invalid'
