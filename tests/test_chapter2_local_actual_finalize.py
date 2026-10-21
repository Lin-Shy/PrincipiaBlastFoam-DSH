import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments/retrieval_method'))
from chapter2_finalize_local_actual_audit import verify_review, sha


def fixture(tmp_path):
    folder=tmp_path/'score';(folder/'requests').mkdir(parents=True)
    source=tmp_path/'manual';source.mkdir();original=source/'one.md';original.write_text('original\n',encoding='utf-8')
    spans={'X':dict(path='manual/one.md',sha256=sha(original),start=1,end=1,
                    lines=[dict(number=1,text='original')])}
    stage=dict(verdict='full',answer_segment_ids=['A1'],reason='actual answer')
    request=folder/'requests/00.json'
    request.write_text(json.dumps(dict(raw_response=dict(choices=[dict(message=dict(content=json.dumps(stage)))]))),encoding='utf-8')
    score=folder/'score.json'
    score.write_text(json.dumps(dict(metrics=dict(complete_valid_answer=1),raw_stage_judgments=[stage])),encoding='utf-8')
    row=dict(question_id='Q1',reviewer_complete=None,local_complete=1,reasoning='Scope ambiguous.',
        changes_to_automatic_score=False,score_sha256=sha(score),request_sha256={'00.json':sha(request)},
        originals=[{k:s[k] for k in ('path','sha256','start','end')} for s in spans.values()],
        reviewed_items=['question','actual candidate','all required hypotheses','all raw stage judgments','bound original source spans'])
    return row,dict(question_id='Q1',original_material=spans),folder,tmp_path


def test_ambiguous_review_remains_unknown_without_changing_local_one(tmp_path):
    args=fixture(tmp_path)
    assert verify_review(*args) is None
    assert json.loads((args[2]/'score.json').read_text())['metrics']['complete_valid_answer']==1


def test_changed_original_rejected(tmp_path):
    args=fixture(tmp_path);(tmp_path/'manual/one.md').write_text('changed\n',encoding='utf-8')
    with pytest.raises(ValueError,match='original-source drift'):verify_review(*args)


def test_omitted_source_review_scope_rejected(tmp_path):
    row,source,folder,root=fixture(tmp_path);row['reviewed_items'].remove('bound original source spans')
    with pytest.raises(ValueError,match='scope incomplete'):verify_review(row,source,folder,root)


def test_replaced_automatic_label_rejected(tmp_path):
    row,source,folder,root=fixture(tmp_path);row['changes_to_automatic_score']=True
    with pytest.raises(ValueError,match='replacement invalid'):verify_review(row,source,folder,root)


def test_changed_raw_judgment_cannot_be_accepted_by_rebinding_request(tmp_path):
    row,source,folder,root=fixture(tmp_path);p=folder/'requests/00.json';data=json.loads(p.read_text())
    data['raw_response']['choices'][0]['message']['content']=json.dumps(dict(verdict='wrong'))
    p.write_text(json.dumps(data),encoding='utf-8');row['request_sha256']['00.json']=sha(p)
    with pytest.raises(ValueError,match='Raw judgment differs'):verify_review(row,source,folder,root)
