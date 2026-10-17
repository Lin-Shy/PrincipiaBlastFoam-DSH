from copy import deepcopy
from pathlib import Path
import sys
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments/retrieval_method'))
from test_chapter2_full_protocol import plan_fixture
from chapter2_full_review import verify_selection
from chapter2_full_protocol import selected_cases


def test_prospective_review_cannot_drop_parent_ablations_or_duplicate_opaque_ids():
    plan=plan_fixture()
    cases=[dict(review_id=f'{i:032x}',cell_id=cell,question_id=qid) for i,(cell,qid) in enumerate(selected_cases(plan))]
    selection=dict(schema='complete_knowledge_qa_review_selection_v4',plan_sha256='a'*64,cases=cases)
    verify_selection(selection,plan,'a'*64)
    assert any('parent_blanket' in r['cell_id'] for r in cases)
    for altered in [dict(selection,cases=cases[:-1]),deepcopy(selection)]:
        if len(altered['cases'])==len(cases):altered['cases'][1]['review_id']=altered['cases'][0]['review_id']
        with pytest.raises(ValueError):verify_selection(altered,plan,'a'*64)
