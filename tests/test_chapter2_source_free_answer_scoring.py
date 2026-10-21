from test_chapter2_reasoning_answer_scoring import sample
from chapter2_source_free_answer_scoring import source_free_requests,parse_source_free_judgments

def test_registered_nonthinking_mode_and_strict_request_binding():
    p,v,r=sample();response=r(v);requests=source_free_requests(p)
    for req,res in zip(requests,response):
        assert req['body']['model']=='qwen3-14b' and req['body']['enable_thinking'] is False
        res['request']=req['body']
    result=parse_source_free_judgments(response,p)
    assert result['rubric_version']=='source_free_v6' and result['metrics']['complete_valid_answer']==0
    response[0]['response']['usage']['completion_tokens']=4097
    assert parse_source_free_judgments(response,p)['reason']=='judge_usage_unknown_or_budget_violation'

def test_null_optional_reasoning_details_do_not_discard_known_usage_or_verdicts():
    p,v,r=sample();response=r(v)
    for req,res in zip(source_free_requests(p),response):
        res['request']=req['body'];res['response']['usage']['completion_tokens_details']=None
    result=parse_source_free_judgments(response,p)
    assert result['status']=='judged' and result['reported_reasoning_tokens']==[None,None,None]
    assert result['metrics']['complete_valid_answer']==0
