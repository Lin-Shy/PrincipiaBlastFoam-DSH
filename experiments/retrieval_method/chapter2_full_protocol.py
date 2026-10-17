"""New complete-activity contracts; never reinterpret the old 150-cell plan."""
from pathlib import Path

from chapter2_knowledge_full_matrix import cells, validate as validate_matrix
from chapter2_knowledge_formal_plan import MODELS, review_policy, digest
from chapter2_v2_retrieval_probe import read, sha

FIELDS = {'schema', 'status', 'dataset_id', 'dataset_seal_sha256', 'sampling_sha256',
    'test_ids', 'budget_ids', 'diagnostic_ids', 'cells', 'models', 'model_budget',
    'knowledge_per_result_characters', 'common_answer_checklist', 'system_prompt_sha256',
    'context_policy', 'context_characters', 'parent_ratio', 'runtime_source_sha256',
    'artifacts_sha256', 'design_sha256', 'development_admission', 'statistics',
    'primary_comparison_family', 'mechanism_comparison_family', 'independent_review',
    'transport_attempts', 'content_retries', 'test_exposure', 'main_baseline_reuse', 'tool_description_policy'}
ARTIFACTS = {'questions', 'corpus_manifest', 'source_map', 'e5_manifest', 'materials',
    'review_receipt', 'tokenizer_qwen3-8b', 'tokenizer_qwen3-14b', 'graph_full',
    'graph_no_cross', 'graph_no_conditions', 'graph_no_extension'}


def is_sha(value):
    return isinstance(value, str) and len(value) == 64 and all(c in '0123456789abcdef' for c in value)


def verify_dataset(dataset, expected_seal):
    dataset = Path(dataset).resolve()
    if sha(dataset / 'dataset-seal.json') != expected_seal:raise ValueError('Dataset seal changed')
    seal = read(dataset / 'dataset-seal.json')
    for name, expected in seal['files'].items():
        path = (dataset / name).resolve()
        if not path.is_relative_to(dataset) or sha(path) != expected:raise ValueError('Sealed dataset changed: ' + name)
    return seal


def validate(plan):
    if set(plan) != FIELDS or plan['schema'] != 'complete_knowledge_qa_activity_v4' or plan['status'] != 'frozen_for_execution':
        raise ValueError('Strict new complete-activity protocol required')
    audit = validate_matrix(plan['cells'], plan['test_ids'], plan['budget_ids'], plan['diagnostic_ids'])
    if plan['models'] != list(MODELS):raise ValueError('Both exact registered models required')
    if plan['tool_description_policy']!='neutral_shared_search_v1':raise ValueError('Identical model-facing retrieval descriptions required')
    if set(plan['artifacts_sha256']) != ARTIFACTS or not plan['runtime_source_sha256']:
        raise ValueError('Complete source and artifact identities required')
    hashes = [*plan['artifacts_sha256'].values(), *plan['runtime_source_sha256'].values(),
        plan['dataset_id'], plan['dataset_seal_sha256'], plan['sampling_sha256'], plan['design_sha256'], plan['system_prompt_sha256']]
    if not all(is_sha(v) for v in hashes):raise ValueError('Invalid SHA256 binding')
    for name in plan['runtime_source_sha256']:
        path = Path(name)
        if path.is_absolute() or '..' in path.parts:raise ValueError('Runtime paths must stay within the snapshot')
    if plan['primary_comparison_family'] != audit['primary_comparisons'] or plan['mechanism_comparison_family'] != audit['mechanism_comparisons']:
        raise ValueError('Registered comparison families changed')
    if plan['independent_review'] != review_policy(plan['diagnostic_ids']):raise ValueError('Source-first review policy changed')
    if plan['statistics'] != dict(unit='linked knowledge group', bootstrap_resamples=10000, seed=20261013,
            repeats_first=True, group_macro=True, multiple_testing='Holm within separate primary and mechanism families',
            unknown_policy='Retain identification bounds; no confirmatory superiority when a paired primary is unknown'):
        raise ValueError('Prospective statistics changed')
    from dataclasses import asdict
    from principia_core.retrieval.knowledge_agent import ModelBudget
    if plan['model_budget'] != asdict(ModelBudget(output_tokens_per_request=4096, final_output_reserve=4096, output_tokens_total=32768)):
        raise ValueError('New common output budget changed')
    if plan['knowledge_per_result_characters'] != 6000 or plan['transport_attempts'] != 1 or plan['content_retries'] != 0:
        raise ValueError('Common delivery or transport policy changed')
    if plan['context_policy'] not in {'adaptive', 'adjacent', 'blanket'} or plan['context_characters'] != 2400 or plan['parent_ratio'] != .5:
        raise ValueError('Development-selected context policy changed')
    admission = plan['development_admission']
    if set(admission) != {'report_sha256', 'generation_protocol_sha256', 'scoring_protocol_sha256', 'selection_sha256', 'positive_outcome_required'}:
        raise ValueError('Bound complete development admission required')
    if admission['positive_outcome_required'] is not False or not all(is_sha(v) for k, v in admission.items() if k != 'positive_outcome_required'):
        raise ValueError('Development admission cannot require a favorable score')
    if plan['test_exposure'] != 'Historically exposed test cohort; not a fresh unseen confirmatory sample':
        raise ValueError('Historical exposure must remain explicit')
    if plan['main_baseline_reuse'] != dict(knowledge_characters=24000, tool_calls=8, source_kind='main',
            question_ids=plan['budget_ids'], same_repeat=True):raise ValueError('Same-repeat budget baselines must be reused')
    return audit


def verify_sources(plan, project):
    for name, expected in plan['runtime_source_sha256'].items():
        path = (Path(project) / name).resolve()
        if not path.is_relative_to(Path(project).resolve()) or sha(path) != expected:raise ValueError('Frozen runtime changed: ' + name)


def selected_cases(plan):
    validate(plan)
    selected = set(plan['diagnostic_ids'])
    return [(c['id'], qid) for c in plan['cells'] for qid in c['question_ids'] if qid in selected]


def method_key(cell):
    return cell['graph_ablation'] if cell['method'] == 'graph' and cell['graph_ablation'] != 'full' else cell['method']


def verify_result(path, question, cell_id, protocol_sha256):
    result = read(path)
    if result.get('formal_result') is not True or result.get('formal_cell_id') != cell_id or result.get('question') != question or result.get('protocol_sha256') != protocol_sha256:
        raise ValueError('Existing result does not belong to this complete activity')
    if read(path.parent / 'result-binding.json') != dict(result_sha256=sha(path), protocol_sha256=protocol_sha256, cell_id=cell_id):
        raise ValueError('Existing formal result integrity changed')
    return result


def pending_jobs(plan, output, questions, protocol_sha256, *, diagnostic=False):
    """Preserve terminal failures and reject an orphan request rather than replay it."""
    pending, existing = [], []
    for cell in plan['cells']:
        if (cell['kind'] == 'complete_material') != diagnostic:continue
        for qid in cell['question_ids']:
            folder = Path(output) / cell['id'] / 'sessions' / qid
            path = folder / 'result.json'
            if path.exists():existing.append(verify_result(path, questions[qid], cell['id'], protocol_sha256))
            else:
                if (folder / 'requests').exists() and any((folder / 'requests').iterdir()):
                    raise ValueError('Orphan physical request must be reconciled before any continuation')
                pending.append(dict(model=cell['model'], cell=cell, question=questions[qid]))
    return pending, existing


def selection_identity(plan):
    return digest(dict(context_policy=plan['context_policy'], context_characters=plan['context_characters'],
        parent_ratio=plan['parent_ratio'], admission=plan['development_admission']))
