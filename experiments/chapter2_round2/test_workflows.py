"""独立评价、人评和付费执行门的边界测试。"""
import hashlib
import json

import pytest
from common import *
from evaluate import evaluate_delivery
from e2e import approval_check
from human_review import kappa,weighted_kappa

class Corpus:
    hashes={'a':'fixedhash','b':'fixedhash2'}
    def lines(self,path):return ['line'+str(n) for n in range(1,7)]

def delivery(spans,cap=6000):
    evidence=[];ledger=[]
    for path,a,b in spans:
        lines=[dict(number=n,text='line'+str(n)) for n in range(a,b+1)]
        evidence.append(dict(path=path,sha256=Corpus.hashes[path],start=a,end=b,lines=lines))
        ledger += [dict(path=path,line=n) for n in range(a,b+1)]
    response=wire(dict(evidence=evidence,truncated=False))
    return dict(id='synthetic',method='test',budget=cap,response=response,response_sha256=hashlib.sha256(response.encode()).hexdigest(),
        response_characters=len(response),delivered_lines=ledger,ranking_seconds=0,delivery_seconds=0,truncated=False)

def annotation(ids):return dict(labels=dict(evidence_integration='multiple',condition_discrimination=False),split_group='synthetic',required_evidence_ids=ids)

EVIDENCE=dict(x=dict(path='a',line_start=1,line_end=4,file_sha256='fixedhash'),
              y=dict(path='b',line_start=2,line_end=3,file_sha256='fixedhash2'))

def test_evidence_union_across_chunks_and_sources():
    result=evaluate_delivery(delivery([('a',1,2),('a',3,4),('b',2,3)]),annotation(['x','y']),EVIDENCE,Corpus())
    assert result['evidence_recall']==result['all_evidence']==1
    assert result['recall_at_1']==0
    assert result['recall_at_3']==1
    assert result['mrr_registered_complete_evidence']==.5

def test_partial_overlap_not_full_evidence():
    result=evaluate_delivery(delivery([('a',2,3)]),annotation(['x','y']),EVIDENCE,Corpus())
    assert result['evidence_recall']==0 and result['all_evidence']==0
    assert result['partial_evidence_overlap']==.25
    assert result['any_evidence_overlap']==1

def test_duplicate_not_inflating_recall():
    result=evaluate_delivery(delivery([('a',1,4),('a',1,4)]),annotation(['x']),EVIDENCE,Corpus())
    assert result['evidence_recall']==1
    assert result['duplicate_line_rate']==.5

def test_budget_and_receipt_tampering_rejected():
    row=delivery([('a',1,4)]);row['response_characters']+=1
    with pytest.raises(ValueError):evaluate_delivery(row,annotation(['x']),EVIDENCE,Corpus())
    row=delivery([('a',1,4)],cap=50)
    with pytest.raises(ValueError):evaluate_delivery(row,annotation(['x']),EVIDENCE,Corpus())

def test_explicit_generation_approval_required(tmp_path):
    protocol=tmp_path/'protocol.json';save(protocol,dict(sessions=1400))
    denied=tmp_path/'denied.json';save(denied,dict(approved=False))
    with pytest.raises(PermissionError):approval_check(denied,protocol)
    valid=tmp_path/'valid.json';save(valid,dict(approved=True,protocol_sha256=sha(protocol),scope='generation',max_sessions=1400,user_instruction='synthetic approval for unit test'))
    assert approval_check(valid,protocol)['sessions']==1400
    insufficient=tmp_path/'insufficient.json';save(insufficient,dict(approved=True,protocol_sha256=sha(protocol),scope='generation',max_sessions=1000,user_instruction='test'))
    with pytest.raises(PermissionError):approval_check(insufficient,protocol)

def test_kappa_reports_class_distribution_and_degeneracy():
    k=kappa(['pass','fail'],['pass','fail'])
    assert k['kappa']==1 and k['left_distribution']=={'pass':1,'fail':1}
    assert kappa(['pass'],['pass'])['kappa'] is None
    assert kappa([],[]) is None
    assert weighted_kappa(['full','partial','wrong'],['full','partial','omitted'])['quadratic_weighted_kappa']==1
    assert weighted_kappa(['unknown'],['full']) is None

def test_real_bge_index_dense_normalized_and_shared_partition():
    import numpy as np
    from text_baselines import BM25
    index=ARCHIVE/'indexes/bge_dense_v1'
    manifest=read(index/'manifest.json');docs=read(index/'passages.json')
    vectors=np.load(index/'embeddings.npy',allow_pickle=False)
    assert manifest['dense_only'] and not manifest['sparse'] and not manifest['colbert']
    assert manifest['revision']=='5617a9f61b028005a4858fdac845db406aefb181'
    assert vectors.shape==(861,1024) and vectors.dtype==np.float32
    assert np.isfinite(vectors).all() and np.max(np.abs(np.linalg.norm(vectors,axis=1)-1))<1e-5
    expected=BM25().docs
    assert [(d['path'],d['start'],d['end'],d['text']) for d in docs]==[(d['path'],d['start'],d['end'],d['text']) for d in expected]
