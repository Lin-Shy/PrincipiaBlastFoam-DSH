from copy import deepcopy
from dataclasses import asdict
from pathlib import Path
import sys
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'experiments/retrieval_method'))
from chapter2_full_protocol import validate, ARTIFACTS, cells, pending_jobs, verify_dataset
from chapter2_knowledge_full_matrix import validate as matrix_audit
from chapter2_knowledge_formal_plan import MODELS, review_policy
from chapter2_v2_retrieval_probe import save, sha
from principia_core.retrieval.knowledge_agent import ModelBudget


def plan_fixture():
    test = [f'Q{i}' for i in range(200)]; budget = test[:40]; diagnostic = test[:16]
    matrix = cells(test, budget, diagnostic); audit = matrix_audit(matrix, test, budget, diagnostic)
    return dict(schema='complete_knowledge_qa_activity_v4', status='frozen_for_execution',
        dataset_id='a'*64, dataset_seal_sha256='b'*64, sampling_sha256='c'*64,
        test_ids=test, budget_ids=budget, diagnostic_ids=diagnostic, cells=matrix, models=list(MODELS),
        model_budget=asdict(ModelBudget(output_tokens_per_request=4096, final_output_reserve=4096, output_tokens_total=32768)),
        knowledge_per_result_characters=6000, common_answer_checklist='common', system_prompt_sha256='d'*64,
        context_policy='adaptive', context_characters=2400, parent_ratio=.5,
        runtime_source_sha256={'runtime.py':'e'*64}, artifacts_sha256={k:'f'*64 for k in ARTIFACTS},
        design_sha256='a'*64, development_admission=dict(report_sha256='a'*64,
            generation_protocol_sha256='b'*64, scoring_protocol_sha256='c'*64, selection_sha256='d'*64, positive_outcome_required=False),
        statistics=dict(unit='linked knowledge group', bootstrap_resamples=10000, seed=20261013,
            repeats_first=True, group_macro=True, multiple_testing='Holm within separate primary and mechanism families',
            unknown_policy='Retain identification bounds; no confirmatory superiority when a paired primary is unknown'),
        primary_comparison_family=audit['primary_comparisons'], mechanism_comparison_family=audit['mechanism_comparisons'],
        independent_review=review_policy(diagnostic), transport_attempts=1, content_retries=0,
        test_exposure='Historically exposed test cohort; not a fresh unseen confirmatory sample',
        main_baseline_reuse=dict(knowledge_characters=24000, tool_calls=8, source_kind='main', question_ids=budget, same_repeat=True))


def test_full_protocol_keeps_complete_scope_and_rejects_budget_or_exposure_drift():
    plan = plan_fixture()
    assert validate(plan)['sessions'] == 17136
    for key, value in [('test_exposure','new unseen test'), ('cells',plan['cells'][:-1]),
            ('parent_ratio',.2), ('transport_attempts',3)]:
        altered = deepcopy(plan); altered[key] = value
        with pytest.raises(ValueError):validate(altered)
    altered = deepcopy(plan); altered['model_budget']['input_tokens_total'] += 1
    with pytest.raises(ValueError):validate(altered)


def test_resume_keeps_terminal_failures_and_rejects_orphan_physical_calls(tmp_path):
    q = dict(id='Q0', question='question')
    cell = dict(id='main/model_method/r01', model='qwen3-8b', kind='main', question_ids=['Q0'])
    plan = dict(cells=[cell]); protocol = 'a'*64
    folder = tmp_path / cell['id'] / 'sessions/Q0'
    result = dict(formal_result=True, formal_cell_id=cell['id'], question=q,
        protocol_sha256=protocol, status='transport_error')
    save(folder/'result.json',result)
    save(folder/'result-binding.json',dict(result_sha256=sha(folder/'result.json'), protocol_sha256=protocol, cell_id=cell['id']))
    jobs, existing = pending_jobs(plan,tmp_path,{'Q0':q},protocol)
    assert not jobs and existing[0]['status'] == 'transport_error'
    q1 = dict(id='Q1',question='another'); cell['question_ids'].append('Q1')
    save(tmp_path/cell['id']/'sessions/Q1/requests/00.json',dict(status='transport_error'))
    with pytest.raises(ValueError,match='Orphan'):pending_jobs(plan,tmp_path,{'Q0':q,'Q1':q1},protocol)


def test_seal_verification_detects_changed_gold_without_rewriting_it(tmp_path):
    save(tmp_path/'scoring/evidence.json',dict(value=1))
    save(tmp_path/'dataset-seal.json',dict(files={'scoring/evidence.json':sha(tmp_path/'scoring/evidence.json')}))
    seal = sha(tmp_path/'dataset-seal.json')
    verify_dataset(tmp_path,seal)
    (tmp_path/'scoring/evidence.json').write_text('{}',encoding='utf-8')
    with pytest.raises(ValueError,match='Sealed dataset'):verify_dataset(tmp_path,seal)
