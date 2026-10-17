"""Complete prospective matrix; extend, never replace, the existing comparison scope."""
from collections import Counter
from copy import deepcopy

from chapter2_knowledge_formal_plan import cells as original_cells, MODELS

PARENT_VARIANTS = ('no_context', 'adjacent_only', 'parent_blanket')
MECHANISMS = ('no_cross', 'no_conditions', 'no_extension', *PARENT_VARIANTS)


def parent_variants(context_policy='adaptive'):
    names={'adaptive':'parent_adaptive','adjacent':'adjacent_only','blanket':'parent_blanket'}
    if context_policy not in names:raise ValueError('Unregistered selected context policy')
    return ('no_context',*[names[p] for p in ('adjacent','adaptive','blanket') if p!=context_policy])


def cells(test_ids, budget_ids, diagnostic_ids, repeats=3, *, context_policy='adaptive'):
    if repeats != 3:raise ValueError('The complete activity retains three repeats')
    result = []
    for cell in original_cells(test_ids, budget_ids, diagnostic_ids, repeats):
        result.append(cell)
        if cell['kind'] == 'ablation' and cell['graph_ablation'] == 'no_extension':
            for variant in parent_variants(context_policy):
                extra = deepcopy(cell); extra['graph_ablation'] = variant
                extra['id'] = f'ablation/{cell["model"]}_graph_{variant}/r{cell["repeat"]:02d}'
                result.append(extra)
    return result


def validate(matrix, test_ids, budget_ids, diagnostic_ids, *, context_policy='adaptive'):
    for name, ids, expected in [('test', test_ids, 200), ('budget', budget_ids, 40), ('diagnostic', diagnostic_ids, 16)]:
        if len(ids) != expected or len(set(ids)) != expected:raise ValueError('Complete unique ' + name + ' cohort required')
    if not set(budget_ids) <= set(test_ids) or not set(diagnostic_ids) <= set(test_ids):raise ValueError('Supplement outside the fixed test cohort')
    if matrix != cells(test_ids, budget_ids, diagnostic_ids,context_policy=context_policy):raise ValueError('Registered methods, repeats or budgets changed')
    if len({c['id'] for c in matrix}) != len(matrix):raise ValueError('Duplicate formal cell identity')
    counts = Counter(); sessions = Counter()
    for c in matrix:counts[c['kind']] += 1; sessions[c['kind']] += len(c['question_ids'])
    if len(matrix) != 168 or sum(sessions.values()) != 17136:raise ValueError('Full matrix denominator changed')
    return dict(cells=len(matrix), sessions=sum(sessions.values()), cells_by_kind=dict(counts), sessions_by_kind=dict(sessions),
        primary_comparisons=[dict(model=m, left='graph', right=r) for m in MODELS for r in ('bm25', 'e5', 'hybrid', 'none')],
        mechanism_comparisons=[dict(model=m, left='graph_full', right=v) for m in MODELS for v in ('no_cross','no_conditions','no_extension',*parent_variants(context_policy))])
