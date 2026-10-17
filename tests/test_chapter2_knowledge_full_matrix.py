from pathlib import Path
import sys
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'experiments/retrieval_method'))
from chapter2_knowledge_formal_plan import cells as original_cells
from chapter2_knowledge_full_matrix import cells, validate, PARENT_VARIANTS


def cohorts():
    test = [f'Q{i:03d}' for i in range(200)]
    return test, test[:40], test[:16]


def test_full_scope_preserves_all_original_cells_and_adds_all_parent_ablations():
    t, b, d = cohorts(); matrix = cells(t, b, d); result = validate(matrix, t, b, d)
    original = {r['id']: r for r in original_cells(t, b, d)}
    assert all(original[r['id']] == r for r in matrix if r['id'] in original)
    assert result['cells'] == 168 and result['sessions'] == 17136
    assert len(result['primary_comparisons']) == 8 and len(result['mechanism_comparisons']) == 12
    for model in ['qwen3-8b', 'qwen3-14b']:
        for variant in PARENT_VARIANTS:
            chosen = [c for c in matrix if c['model'] == model and c['graph_ablation'] == variant]
            assert len(chosen) == 3 and all(c['question_ids'] == t and c['tool_calls'] == 8 and c['knowledge_characters'] == 24000 for c in chosen)


def test_scope_validator_rejects_selective_method_or_question_drops():
    t, b, d = cohorts(); matrix = cells(t, b, d)
    with pytest.raises(ValueError):validate(matrix[:-1], t, b, d)
    matrix[0]['question_ids'] = matrix[0]['question_ids'][:-1]
    with pytest.raises(ValueError):validate(matrix, t, b, d)


def test_budget_controls_reference_main_repeat_without_extra_resampling():
    t, b, d = cohorts(); matrix = cells(t, b, d)
    for c in matrix:
        if c['kind'] in {'knowledge_budget', 'decision_budget'}:
            main = next(v for v in matrix if v['kind'] == 'main' and v['model'] == c['model'] and v['method'] == c['method'] and v['repeat'] == c['repeat'])
            assert set(c['question_ids']) <= set(main['question_ids'])
    with pytest.raises(ValueError):cells(t, b, d, repeats=1)
