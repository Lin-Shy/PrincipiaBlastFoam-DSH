"""Frozen single attempts, isolated scoring prompts and new-graph ablations."""
import json
from pathlib import Path
import sys
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments/retrieval_method'))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from chapter2_judge_200 import call_once
from chapter2_judge_200_rubric import requests
from chapter2_knowledge_graph_variants import variant
from chapter2_knowledge_graph_v6 import BilingualScopeGraph
from chapter2_build_graph_v5 import augment
from test_chapter2_graph_source_context import fixture


def test_closed_judge_failure_is_reused_but_never_reissued(tmp_path):
    class Client:
        folder=tmp_path
        def __call__(self,*args):raise AssertionError('No repeated model request')
    body={'model':'qwen3-14b'}
    p=tmp_path/'00.json';p.write_text(json.dumps(dict(request=body,status='transport_error')),encoding='utf-8')
    assert call_once(Client(),body,0)['status']=='transport_error'
    p.write_text(json.dumps(dict(request=body,status='in_flight')),encoding='utf-8')
    with pytest.raises(ValueError):call_once(Client(),body,0)


def test_coverage_prompt_cannot_receive_source_or_question_condition_truth():
    payload=dict(answer='Actual answer.',question='Question with a binding constraint.',
        original_material={'E1':{'text':'secret source truth'}},
        rubric=dict(required_points=[dict(id='K1',claim='Required claim.')],condition_discrimination=True,applicability='scope'))
    rows=requests(payload)
    coverage=json.loads(rows[0]['body']['messages'][-1]['content'])
    audit=json.loads(rows[-1]['body']['messages'][-1]['content'])
    assert set(coverage)=={'premise_segments','premise_answer','hypothesis'}
    assert 'secret source truth' not in rows[0]['body']['messages'][-1]['content']
    assert audit['question']==payload['question'] and audit['condition_required'] is True


def test_new_alias_graph_no_cross_cannot_return_context_from_other_owners(tmp_path):
    graph,old=fixture(tmp_path,{'manual/a.md':'# Models\n## GammaLaw\npressure equation\n## Other\nextra\n',
        'tutorials/demo/constant/p':'FoamFile\n{\n class dictionary;\n object p;\n}\nequationOfState GammaLaw;'})
    graph=augment(graph);revised,audit=variant(graph,'no_cross')
    assert audit['cross_owner_edges_after']==0 and revised['units']==graph['units']
    path=tmp_path/'no_cross.json';path.write_text(json.dumps(revised),encoding='utf-8')
    engine=BilingualScopeGraph(path,old.root,corpus_manifest=tmp_path/'authority.json',options={'with_cross':False})
    packet=engine.read_native(engine.rank('GammaLaw equationOfState'))
    assert all(all(v['owner']==row['owner'] for v in row['context_fragments']) for row in packet['items'])
