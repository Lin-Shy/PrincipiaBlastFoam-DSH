from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from common import read,sha,save
import resume_scoring as continuation
from resume_generation import safe_save

def test_unicode_detection_is_lossless_and_uniform():
    assert not continuation.invalid_unicode(dict(status='answered',answer='正常中文😀',references=[]))
    for arm in ['graph','bm25','bge_m3','bm25_bge_m3','bm25_parent','no_traversal','anchor_only']:
        assert continuation.invalid_unicode(dict(arm=arm,status='answered',answer='raw\udb07text',references=[]))
    assert not continuation.invalid_unicode(dict(status='completion_truncated',answer=None,references=None))

def test_canonical_view_preserves_original_receipts_and_other_results(tmp_path,monkeypatch):
    old=tmp_path/'old';new=tmp_path/'new';monkeypatch.setattr(continuation,'OLD',old);monkeypatch.setattr(continuation,'NEW',new)
    arm='fixture';root=old/arm;bindings={}
    for i in range(200):
        qid=str(i);folder=root/'generation'/qid
        result=dict(id=qid,arm=arm,status='answered',answer='bad\udb07'if i==0 else 'good',references=[],references_delivered=True)
        safe_save(folder/'result.json',result);save(folder/'requests/00.json',dict(fixture=i))
        bindings[qid]=sha(folder/'result.json')
    save(root/'completed.json',dict(questions=200,results_sha256=bindings))
    before={str(p.relative_to(old)):sha(p)for p in old.rglob('*')if p.is_file()}
    continuation.copy_arm(arm)
    assert before=={str(p.relative_to(old)):sha(p)for p in old.rglob('*')if p.is_file()}
    assert read(new/arm/'generation/0/result.json')['status']=='invalid_unicode_output'
    assert sha(new/arm/'generation/0/original_result.json')==bindings['0']
    assert sha(new/arm/'generation/1/result.json')==bindings['1']
    assert all(sha(p)==sha(new/p.relative_to(old))for p in old.rglob('requests/*.json'))
    assert len(read(new/'canonical_closures/fixture.json')['changes'])==1
