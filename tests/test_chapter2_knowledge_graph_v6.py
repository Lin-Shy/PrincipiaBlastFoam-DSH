"""Semantic source labels can boost candidates without overriding hard scopes."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'experiments/retrieval_method'))
from chapter2_knowledge_graph_v6 import BilingualScopeGraph, alias_relevance, chinese_terms
from test_chapter2_graph_source_context import fixture


def test_short_generic_overlap_cannot_activate_a_case_prior():
    assert alias_relevance('计算压力', chinese_terms('计算压力'), ['压力模型']) == 0
    assert alias_relevance('如何求爆炸冲量', chinese_terms('如何求爆炸冲量'), ['爆炸冲量']) == 1


def test_alias_case_prior_never_excludes_other_cases_or_bypasses_manual_scope(tmp_path):
    graph, old = fixture(tmp_path, {
        'manual/a.md':'# Models\npressure source\n',
        'tutorials/solver/demo/README.md':'# An example\npressure source\n',
        'tutorials/solver/demo/0/p':'internalField uniform 1;',
        'tutorials/solver/other/0/p':'internalField uniform 2;'})
    for node in graph['nodes'].values():
        if node['kind']=='original_unit' and node['path'].endswith('/README.md'):
            node['aliases']=['轴对称爆炸'];node['alias_grounding']=[dict(quote='An example')]
    path=tmp_path/'bilingual.json';path.write_text(json.dumps(graph), encoding='utf-8')
    engine=BilingualScopeGraph(path, old.root, corpus_manifest=tmp_path/'authority.json', semantic_policy='case')
    ranking=engine.rank('轴对称爆炸 internalField')
    assert any('/other/' in r['path'] for r in ranking['items'])
    assert any(r['reasons'].get('soft_case_source_alias_bonus',0)>0 for r in ranking['items'])
    manual=engine.rank('只依据手册解释轴对称爆炸 pressure')
    assert manual['items'] and all(r['path'].startswith('manual/') for r in manual['items'])
