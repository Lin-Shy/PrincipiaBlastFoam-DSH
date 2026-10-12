import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest

SKILL = Path(__file__).resolve().parents[1] / '.dsh/skills/blastfoam-knowledge'
sys.path.insert(0, str(SKILL / 'scripts'))
if not (SKILL/'scripts/graph_query.py').exists():
    pytest.skip('用户已移除旧分页语义试验；新章节图由 test_manual_graph.py 验证', allow_module_level=True)
spec = importlib.util.spec_from_file_location('pilot_graph_query', SKILL / 'scripts/graph_query.py')
g = importlib.util.module_from_spec(spec)
spec.loader.exec_module(g)


@pytest.fixture(scope='module')
def graph():
    return g.PilotGraph(SKILL)


def test_lookup_preserves_requirement_recommendation_and_evidence(graph):
    result = graph.query('impulse', context={'burstModel': 'impulse'})
    assert result['entity'] == 'burst/impulse'
    facts = {f['relation']: f for f in result['results']}
    assert facts['REQUIRES_AVAILABLE']['modality'] == 'required'
    assert facts['RECOMMENDS']['object']['alternatives_allowed'] is True
    assert all(f['condition_state'] == 'true' and f['evidence'] for f in facts.values())
    assert all(f['publication'] == 'quarantined' and not f['executable'] for f in facts.values())


def test_scope_navigation_is_explicit_and_not_physical_inference(graph):
    result = graph.query('setRefinedFields', ['CONFIGURED_IN'], {'utility': 'setRefinedFields'})
    fact = result['results'][0]
    assert fact['object']['file'] == 'setFieldsDict'
    assert fact['graph_path'][0]['origin'] == 'identifier_prefix_navigation'
    assert fact['graph_path'][-1]['relation'] == 'CONFIGURED_IN'


def test_unknown_and_false_default_conditions_are_not_promoted(graph):
    unknown = graph.query('EOS/JWL/e0', context={'equationOfState': 'JWL'})
    assert unknown['results'][0]['condition_state'] == 'unknown'
    assert unknown['results'][0]['missing_context_fields'] == ['material_state']
    false = graph.query('EOS/JWL/e0', context={'equationOfState': 'JWL', 'material_state': 'solid'})
    assert false['status'] == 'no_applicable_fact' and not false['results']
    assert false['excluded'][0]['reason'] == 'condition_false'


def test_unknown_branch_and_untranscribed_formula_stay_unanswered(graph):
    result = graph.query('blastFoam', ['SELECTS_MODE'],
                         {'solver': 'blastFoam', 'phases_keyword_present': True, 'phase_count': 1})
    assert result['status'] == 'no_applicable_fact'
    assert result['deferred'][0]['status'] == 'not_established_by_selected_source'
    result = graph.query('JWL', ['DEFINED_BY'])
    assert result['status'] == 'relation_not_covered'
    assert result['deferred'][0]['status'] == 'deferred_transcription'


def test_ambiguous_leaf_never_silently_selects_one(graph, monkeypatch):
    entities = dict(graph.entities)
    entities['other/impulse'] = entities['burst/impulse']
    monkeypatch.setattr(graph, 'entities', entities)
    result = graph.query('impulse')
    assert result['status'] == 'ambiguous_entity' and len(result['entity_candidates']) == 2
    assert graph.query('burst/impulse')['status'] == 'ok'


def test_missing_entity_relation_and_invalid_requests_are_distinct(graph):
    assert graph.query('EOS/solidJWL')['status'] == 'entity_not_found'
    assert graph.query('impulse', ['HAS_UNIT'])['status'] == 'relation_not_covered'
    for kwargs in ({'relations': ['TYPO']}, {'context': []}, {'limit': 0}):
        with pytest.raises(ValueError):
            graph.query('impulse', **kwargs)


def test_budget_reports_omissions_and_order_is_repeatable(graph):
    result = graph.query('JWL', limit=1)
    assert len(result['results']) == 1 and result['truncated'] and result['total_matches'] == 5
    assert graph.query('JWL', limit=1) == result


def test_cli_requires_pilot_flag_and_works_without_retrieval_modules():
    script = SKILL / 'scripts/graph_query.py'
    p = subprocess.run([sys.executable, str(script), '--entity', 'impulse'], capture_output=True, text=True)
    assert p.returncode != 0 and '--experimental-pilot' in p.stderr
    # Prohibit importing either lexical retrieval module in an isolated interpreter.
    code = """
import runpy,sys
sys.modules['knowledge']=None
sys.modules['ranking']=None
sys.path.insert(0,sys.argv[1])
script=sys.argv[2]
sys.argv=[script,'--experimental-pilot','--entity','impulse']
runpy.run_path(script,run_name='__main__')
"""
    p = subprocess.run([sys.executable, '-c', code, str(script.parent), str(script)],
                       capture_output=True, text=True, check=True)
    assert json.loads(p.stdout)['entity'] == 'burst/impulse'
