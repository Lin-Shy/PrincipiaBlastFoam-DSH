"""Observable invariants of the standalone skill, using an isolated small corpus."""
import importlib.util
import json
from pathlib import Path
import shutil

import pytest

SKILL = Path(__file__).resolve().parents[1] / '.dsh/skills/blastfoam-knowledge'
spec = importlib.util.spec_from_file_location('blastfoam_knowledge', SKILL / 'scripts/knowledge.py')
k = importlib.util.module_from_spec(spec)
spec.loader.exec_module(k)


@pytest.fixture
def workspace(tmp_path):
    corpus = tmp_path / 'corpus'
    (corpus / 'manual/markdown').mkdir(parents=True)
    (corpus / 'tutorials/demo/system').mkdir(parents=True)
    (corpus / 'tutorials/demo/constant').mkdir()
    (corpus / 'manual/markdown/01_models.md').write_text('# Activation Models\n\n## 1.1 linear\n\nlinear activation model vDet\n')
    (corpus / 'tutorials/demo/Allrun').write_text('runApplication blockMesh\nrunApplication setRefinedFields\n')
    (corpus / 'tutorials/demo/system/controlDict').write_text('FoamFile {version 2.0;} application blastFoam;')
    (corpus / 'tutorials/demo/constant/phaseProperties').write_text('FoamFile {version 2.0;} c4 { activationModel linear; }')
    (corpus / 'tutorials/demo/README.md').write_text('Uses linear activation model and STL building mesh.')
    return corpus, tmp_path / 'index'


def test_parser_preserves_scope_expressions_lists_and_duplicate_keys():
    text = '''// ignore
    phases { air {rho 1.2;} c4 {rho 1600; points ((0 0 0) (1 0 0));
    rho $reference; dims [1 -3 0 0 0 0 0]; } }
    #include "shared"
    endTime 0.1;
    '''
    entries, issues = k.parse_dictionary(text)
    values = {e['dictionary_path']: e for e in entries}
    assert values['phases/air/rho']['value'] == '1.2'
    assert values['phases/c4/rho']['value'] == '1600'
    assert not values['phases/c4/rho@2']['resolved']
    assert values['phases/c4/points']['value'] == '((0 0 0) (1 0 0))'
    assert values['phases/c4/dims']['value'] == '[1 -3 0 0 0 0 0]'
    assert values['endTime']['value'] == '0.1'
    assert any(x['reason'] == 'directive_preserved' for x in issues)


def test_incremental_edit_delete_and_clean_build_equivalence(workspace):
    corpus, index = workspace
    first = k.build(SKILL, corpus, index)
    assert first['parsed_files'] == 4
    assert k.build(SKILL, corpus, index)['status'] == 'unchanged'
    phase = corpus / 'tutorials/demo/constant/phaseProperties'
    phase.write_text(phase.read_text().replace('linear','pressureBased'))
    with pytest.raises(ValueError, match='corpus changed'):
        k.query('activation',skill=SKILL,corpus=corpus,index=index)
    second = k.build(SKILL, corpus, index)
    assert second['parsed_files'] == 1 and second['reused_files'] == 3
    graph = k.read_json(k.release_path(index) / 'graph.json')
    assert any(i['reason'] == 'readme_configuration_conflict' for i in graph['issues'])
    assert not any(e['relation'] == 'REFERS_TO_DEFINITION' for e in graph['edges'])
    fresh = index.parent / 'fresh'
    k.build(SKILL, corpus, fresh)
    assert (k.release_path(index) / 'graph.json').read_bytes() == (k.release_path(fresh) / 'graph.json').read_bytes()
    shutil.rmtree(corpus / 'tutorials/demo')
    k.build(SKILL, corpus, index)
    graph = k.read_json(k.release_path(index) / 'graph.json')
    assert not any(n['kind'] == 'case' for n in graph['nodes'])
    assert any(n['kind'] == 'manual_section' for n in graph['nodes'])
    assert k.query('building',case='demo',skill=SKILL,corpus=corpus,index=index)['status'] == 'case_unavailable'


def test_addition_include_reference_and_failure_preserves_pointer(workspace, monkeypatch):
    corpus, index = workspace
    k.build(SKILL, corpus, index)
    shutil.copytree(corpus / 'tutorials/demo', corpus / 'tutorials/added')
    shared=corpus / 'tutorials/added/shared'
    shared.write_text('value 1;')
    (corpus / 'tutorials/added/system/controlDict').write_text('#include "../shared"\napplication blastFoam;')
    k.build(SKILL, corpus, index)
    graph=k.read_json(k.release_path(index) / 'graph.json')
    assert any(n['id']=='case:tutorials/added' for n in graph['nodes'])
    assert any(e['relation']=='INCLUDES' and e['target']=='file:tutorials/added/shared' for e in graph['edges'])
    before=(index / 'current.json').read_bytes()
    shared.write_text('value 2;')
    def fail(*args):
        raise ValueError('injected validation failure')
    monkeypatch.setattr(k,'check_release',fail)
    with pytest.raises(ValueError,match='injected'):
        k.build(SKILL, corpus, index)
    assert (index / 'current.json').read_bytes()==before


def test_retrieval_expands_selector_definition_and_source_is_bounded(workspace):
    corpus,index=workspace
    k.build(SKILL,corpus,index)
    r=k.query('activationModel',mode='search',case='demo',limit=4,skill=SKILL,corpus=corpus,index=index)
    assert any(e['relation']=='REFERS_TO_DEFINITION' for e in r['graph_relations'])
    assert any(e['evidence']['path']=='manual/markdown/01_models.md' for e in r['related_evidence'])
    reverse=k.query('linear examples',mode='manual',limit=3,skill=SKILL,corpus=corpus,index=index)
    assert any(e['evidence']['path']=='tutorials/demo/constant/phaseProperties' for e in reverse['related_evidence'])
    assert k.source('tutorials/demo/constant/phaseProperties',skill=SKILL,corpus=corpus,index=index)['text']
    with pytest.raises(ValueError):
        k.source('../outside',skill=SKILL,corpus=corpus,index=index)


def test_utility_step_links_manual_and_same_file_hits_do_not_fill_budget(workspace):
    corpus,index=workspace
    (corpus/'manual/markdown/02_utilities.md').write_text('# Utilities\n\n## 2.1 setRefinedFields\n\nsetRefinedFields initializes fields.\n')
    k.build(SKILL,corpus,index)
    r=k.query('Allrun setRefinedFields',mode='search',limit=3,skill=SKILL,corpus=corpus,index=index)
    paths=[h['evidence']['path'] for h in r['results']]
    assert len(paths)==len(set(paths))
    assert any(e['status']=='exact_utility_name_match' for e in r['graph_relations'])


def test_alias_dedup_and_canonical_deletion_preserves_remaining_case(workspace):
    corpus,index=workspace
    canonical=corpus/'tutorials/blastFoam/internalDetonation/internalDetonation_withObstacleAndGlass'
    alias=corpus/'tutorials/setRefinedFields/internalDetonation_withObstacleAndGlass'
    shutil.copytree(corpus/'tutorials/demo',canonical)
    shutil.copytree(canonical,alias)
    k.build(SKILL,corpus,index)
    graph=k.read_json(k.release_path(index)/'graph.json')
    assert graph['aliases']
    assert not any(n['id']=='case:'+alias.relative_to(corpus).as_posix() for n in graph['nodes'])
    shutil.rmtree(canonical)
    k.build(SKILL,corpus,index)
    graph=k.read_json(k.release_path(index)/'graph.json')
    assert not graph['aliases']
    assert any(n['id']=='case:'+alias.relative_to(corpus).as_posix() for n in graph['nodes'])


def test_ranking_is_edge_order_invariant_and_does_not_count_duplicate_votes(workspace,monkeypatch):
    corpus,index=workspace
    shutil.copytree(corpus/'tutorials/demo',corpus/'tutorials/other')
    k.build(SKILL,corpus,index)
    args=dict(mode='manual',limit=4,skill=SKILL,corpus=corpus,index=index)
    expected=k.query('linear examples',**args)
    reader=k.read_json
    def permuted(path):
        value=reader(path)
        if path.name=='graph.json':
            value['edges']=list(reversed(value['edges']))+value['edges']
            value['nodes']=list(reversed(value['nodes']))
        return value
    monkeypatch.setattr(k,'read_json',permuted)
    actual=k.query('linear examples',**args)
    assert actual['results']==expected['results']
    assert actual['graph_relations']==expected['graph_relations']


def test_evidence_budget_scope_and_reverse_gating(workspace):
    corpus,index=workspace
    shutil.copytree(corpus/'tutorials/demo',corpus/'tutorials/other')
    k.build(SKILL,corpus,index)
    for budget in (1,2,4):
        r=k.query('linear activationModel',mode='search',case='demo',limit=budget,skill=SKILL,corpus=corpus,index=index)
        assert len(r['results'])<=budget
        assert len({h['evidence']['path'] for h in r['results']})==len(r['results'])
        assert all(h['case'] in (None,'tutorials/demo') for h in r['results'])
        assert all(h in r['results'] for h in r['related_evidence'])
        assert all(len(h['graph_path']['edges'])<=3 for h in r['related_evidence'])
    manual=k.query('linear',mode='manual',limit=8,skill=SKILL,corpus=corpus,index=index)
    assert all(h['source_scope']=='manual' for h in manual['results'])


def test_conflict_path_reaches_actual_definition_without_case_specific_rules(workspace):
    corpus,index=workspace
    (corpus/'tutorials/demo/README.md').write_text('Uses pressureBased activation model, discrepancy in documentation.')
    k.build(SKILL,corpus,index)
    r=k.query('README discrepancy',mode='search',case='demo',limit=8,skill=SKILL,corpus=corpus,index=index)
    page=next(h for h in r['related_evidence'] if h['evidence']['path']=='manual/markdown/01_models.md')
    assert [e['relation'] for e in page['graph_path']['edges']]==['CONFLICTS_WITH','REFERS_TO_DEFINITION','DOCUMENTED_ON']


def test_function_shaped_dictionary_keys_are_not_list_values():
    text = """divSchemes
{
    div(phi,U) Gauss upwind;
    div(((rho*nuEff)*dev2(T(grad(U))))) Gauss linear;
}
interpolationSchemes { reconstruct(rho) vanAlbada; }
points ((0 0 0) (1 1 1));
"""
    entries, issues = k.parse_dictionary(text)
    got = {n['dictionary_path']: n['value'] for n in entries}
    assert got == {
        'divSchemes/div(phi,U)': 'Gauss upwind',
        'divSchemes/div(((rho*nuEff)*dev2(T(grad(U)))))': 'Gauss linear',
        'interpolationSchemes/reconstruct(rho)': 'vanAlbada',
        'points': '((0 0 0) (1 1 1))',
    }
    assert not issues
