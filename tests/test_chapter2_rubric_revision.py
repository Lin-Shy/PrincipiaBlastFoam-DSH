from copy import deepcopy
from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments/retrieval_method'))
from chapter2_derive_rubric_revision import revise


def annotation():
    return [dict(id='D',required_points=[dict(id='K1',claim='Meaning and default 10',weight=1),dict(id='K2',claim='Other requested fact',weight=1)])]


def decision():
    return dict(question_id='D',point_id='K1',old_claim='Meaning and default 10',new_claim='Default 10',reason='Meaning is not requested',question_basis='What is the default?',source_basis='Original says default 10')


def test_revision_keeps_weight_and_input_and_requires_original_claim_identity():
    original=annotation();before=deepcopy(original)
    revised,ledger=revise(original,[decision()],{'D'})
    assert original==before and revised[0]['required_points'][0]['weight']==1
    assert revised[0]['required_points'][0]['claim']=='Default 10'
    bad=decision();bad['old_claim']='different claim'
    with pytest.raises(ValueError,match='original claim'):revise(original,[bad],{'D'})


def test_test_items_and_empty_point_sets_cannot_be_silently_removed():
    with pytest.raises(ValueError,match='development'):revise(annotation(),[decision()],{'OTHER'})
    original=annotation();original[0]['required_points']=original[0]['required_points'][:1]
    change=decision();change['new_claim']=None
    with pytest.raises(ValueError,match='every mandatory'):revise(original,[change],{'D'})


def test_each_edit_needs_source_and_question_reasons():
    change=decision();change['source_basis']=''
    with pytest.raises(ValueError,match='question/source'):revise(annotation(),[change],{'D'})


def test_removed_background_point_has_no_dangling_contribution_or_omission_rule():
    original=annotation();original[0].update(source_contributions={'S':['K1','K2']},critical_errors=['Omitted unasked background','Actual wrong claim'])
    change=decision();change.update(new_claim=None,remove_critical_errors=['Omitted unasked background'])
    revised,_=revise(original,[change],{'D'})
    assert revised[0]['source_contributions']=={'S':['K2']}
    assert revised[0]['critical_errors']==['Actual wrong claim']
    assert original[0]['source_contributions']['S']==['K1','K2']
