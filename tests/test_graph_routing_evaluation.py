import importlib.util
import json
from pathlib import Path

import pytest

PATH = Path(__file__).resolve().parents[1] / 'experiments/retrieval_method/evaluate_graph_routing.py'
spec = importlib.util.spec_from_file_location('routing_eval', PATH)
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)


def annotation():
    return {'id': 'test', 'group': 'source_lookup',
            'reference_request': {'entity': 'model/name', 'relations': ['HAS_DEFAULT'], 'context': {'model': 'name'}},
            'expected': {'status': 'ok', 'fact_ids': ['fact'], 'condition_states': {'fact': 'unknown'},
                         'support_pages': [12]}}


def record():
    return {'response': {'status': 'ok'},
            'prediction': {'action': 'query', 'request': annotation()['reference_request']},
            'execution': {'status': 'ok', 'results': [{'id': 'fact', 'condition_state': 'unknown',
                                                     'evidence': [{'pdf_page': 12}]}]}}


def test_model_messages_do_not_accept_annotated_rows():
    catalog = {'entities': [{'id': 'model/name'}]}
    with pytest.raises(ValueError):
        r.messages({'query': 'q', 'expected': 'SECRET_LABEL'}, catalog, 'prompt')
    result = r.messages('q', catalog, 'prompt')
    assert json.loads(result[1]['content']) == {'question': 'q', 'catalog': catalog}


@pytest.mark.parametrize('payload', [
    {'action': 'uncovered', 'request': {'entity': 'x'}},
    {'action': 'query', 'request': {'entity': 'x', 'relations': [], 'context': {}}},
    {'action': 'query', 'request': {'entity': 'x', 'relations': ['R'], 'context': []}},
])
def test_invalid_plans_are_not_silently_repaired(payload):
    with pytest.raises(ValueError):
        r.parse_prediction(json.dumps(payload))


def test_scoring_detects_guessed_context_and_unknown_promotion():
    sample = record()
    sample['prediction']['request']['context']['material_state'] = 'gas'
    sample['execution']['results'][0]['condition_state'] = 'true'
    score = r.score_case(annotation(), sample)
    assert score['fact_recall'] == 1
    assert not score['context_faithful'] and not score['condition_states_match']
    assert not score['outcome_matches_reference']


def test_scope_equivalent_query_need_not_equal_reference():
    sample = record()
    sample['prediction']['request']['entity'] = 'model/name/parameter'
    score = r.score_case(annotation(), sample)
    assert not score['exact_reference_request']
    assert score['outcome_matches_reference']


def test_missing_run_is_failure_not_successful_abstention():
    a = annotation()
    a['group'] = 'boundary'
    a['expected'] = {'status': 'entity_not_found', 'fact_ids': [], 'condition_states': {}, 'support_pages': []}
    assert not r.score_case(a, {})['outcome_matches_reference']
    explicit = {'response': {'status': 'ok'}, 'prediction': {'action': 'uncovered', 'request': None},
                'execution': {'status': 'uncovered', 'results': []}}
    assert r.score_case(a, explicit)['outcome_matches_reference']


def test_extra_facts_reduce_precision_despite_full_recall():
    sample = record()
    sample['execution']['results'].append({'id': 'other', 'condition_state': 'true', 'evidence': [{'pdf_page': 15}]})
    score = r.score_case(annotation(), sample)
    assert score['fact_recall'] == 1 and score['fact_precision'] == 0.5
    assert not score['outcome_matches_reference']
