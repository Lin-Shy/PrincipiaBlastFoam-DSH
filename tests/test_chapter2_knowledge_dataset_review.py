"""Reviewer schema must not silently admit incomplete or mislabeled evidence."""
import importlib.util
import json
from pathlib import Path
import pytest

FILE = Path(__file__).parents[1] / 'experiments/retrieval_method/chapter2_review_knowledge_dataset.py'
SPEC = importlib.util.spec_from_file_location('knowledge_review', FILE)
review = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(review)

def case():
    body = {'messages': [{}, {'content': json.dumps({'questions_and_annotations': [
        {'id': 'q1', 'labels': {'evidence_integration': 'multiple'}, 'required_points': [{'id':'k1'}, {'id':'k2'}]}],
        'sources': {'s1': {}, 's2': {}}})}]}
    row = {'id':'q1', 'question_clear':True, 'source_sufficient':True, 'scope_valid':True,
        'integration_label_valid':True, 'condition_label_valid':True, 'critical_errors_valid':True,
        'single_source_shortcut':False, 'issues':[], 'point_reviews':[
            {'id':'k1','supported':True,'reason':'source1 supports k1'},
            {'id':'k2','supported':True,'reason':'source2 supports k2'}]}
    return body, row

def response(row, model='deepseek-flash'):
    return {'model':model, 'choices':[{'message':{'content':json.dumps({'reviews':[row]})}}]}

def test_source_shortcut_requires_author_action():
    body, row = case()
    row['single_source_shortcut'] = 's1'
    assert review.parse_review(response(row), body)['reviews'][0]['author_action_required']

def test_unsupported_point_requires_author_action():
    body, row = case()
    row['point_reviews'][1]['supported'] = False
    assert review.parse_review(response(row), body)['reviews'][0]['author_action_required']

def test_missing_point_not_admitted_as_complete_review():
    body, row = case()
    row['point_reviews'].pop()
    with pytest.raises(ValueError, match='point review ids'):
        review.parse_review(response(row), body)

def test_other_model_not_admitted_as_exact_offline_review():
    body, row = case()
    with pytest.raises(ValueError, match='model identity'):
        review.parse_review(response(row, 'qwen3-8b'), body)

def test_string_true_not_admitted_as_verdict():
    body, row = case()
    row['source_sufficient'] = 'true'
    with pytest.raises(ValueError, match='bool fields'):
        review.parse_review(response(row), body)
