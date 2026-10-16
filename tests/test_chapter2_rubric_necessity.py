import json
from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments/retrieval_method'))
from chapter2_review_rubric_necessity import body,parse_proposal,parse_verification,REVIEW,VERIFY


def payload():
    return dict(id='D1',question='What is the default?',annotation={'required_points':[{'id':'K1','claim':'Meaning and default.'}]},sources={'E1':{}})


def proposal():
    return dict(question_id='D1',question_issues=[],points=[dict(id='K1',classification='required',required_claim='Default is 10.',optional_background=['Meaning of the parameter'],reason='Only default is asked.')],missing_requirements=[])


def test_question_and_original_sources_only_not_candidate_scores():
    request=body(REVIEW,payload())
    assert request['model']=='deepseek-flash'
    assert json.loads(request['messages'][1]['content'])==payload()
    assert parse_proposal(proposal(),request)==proposal()


def test_every_old_point_must_be_reviewed_even_when_reclassified():
    value=proposal();value['points']=[]
    with pytest.raises(ValueError,match='Every original point'):parse_proposal(value,body(REVIEW,payload()))


def test_added_requirements_need_original_source_ids():
    value=proposal();value['missing_requirements']=[dict(claim='Missing condition',evidence_ids=['invented'],reason='Needed')]
    with pytest.raises(ValueError,match='original source'):parse_proposal(value,body(REVIEW,payload()))


def test_independent_verification_requires_actual_booleans():
    value=dict(question_id='D1',points=[dict(id='K1',proposal_valid=True,reason='Supported')],additions_valid='true',question_scope_clear=True,reason='Clear')
    with pytest.raises(ValueError,match='Boolean'):parse_verification(value,body(VERIFY,{**payload(),'proposal':proposal()}))
