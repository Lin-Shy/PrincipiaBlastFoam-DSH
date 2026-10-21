import json
import pytest
from test_chapter2_reasoning_answer_scoring import sample
from chapter2_scoped_answer_scoring import scoped_requests,parse_scoped_judgments,delivery_scope
from chapter2_source_free_answer_scoring import source_free_requests

def test_receipt_originals_only_enter_truth_stage_and_old_requests_are_rejected():
    p,v,r=sample();p['delivery_scope']={'receipt_known':True,'original_spans':[{'text':'RECEIPT_SECRET'}]}
    requests=scoped_requests(p)
    assert all('RECEIPT_SECRET' not in json.dumps(row) for row in requests[:-1])
    assert 'RECEIPT_SECRET' in json.dumps(requests[-1])
    responses=r(v)
    for req,res in zip(source_free_requests(p),responses):res['request']=req['body']
    assert parse_scoped_judgments(responses,p)['reason']=='reasoning_judge_request_binding_mismatch'

def test_v8_preserves_omission_bound_without_repairing_missing_condition():
    p,v,r=sample();p['rubric']['condition_discrimination']=True
    responses=r(v)
    for req,res in zip(scoped_requests(p),responses):res['request']=req['body']
    result=parse_scoped_judgments(responses,p)
    assert result['status']=='partially_judged' and result['rubric_version']=='source_scoped_v8'
    assert result['metrics']['complete_upper']==0 and result['metrics']['factuality']=='unknown'

def test_receipt_reconstruction_deduplicates_original_lines_and_rejects_extra_labels():
    class Corpus:
        def read(self,path,start,end):return {'path':path,'start':start,'end':end,'sha256':'bound'}
    lines=[{'path':'original','line':n} for n in [3,1,2,3,6]]
    value=delivery_scope(Corpus(),lines)
    assert value['original_spans']==[{'path':'original','start':1,'end':3,'sha256':'bound'},
      {'path':'original','start':6,'end':6,'sha256':'bound'}]
    with pytest.raises(ValueError):delivery_scope(Corpus(),[{'path':'original','line':1,'method':'hidden'}])
