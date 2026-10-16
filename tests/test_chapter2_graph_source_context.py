import json
from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments/retrieval_method'))
from test_chapter2_graph_sources import corpus as make_corpus
from chapter2_graph_sources import prepare_sources
from chapter2_compile_knowledge_graph import compile_graph
from chapter2_graph_source_context import add_source_context,case_aliases,source_case
from chapter2_knowledge_graph_v3 import SourceContextGraph


def fixture(tmp_path,files,**options):
    corpus=make_corpus(tmp_path,files)
    graph=compile_graph(prepare_sources(corpus),[],corpus.hashes,complete=True,binding={})
    graph=add_source_context(graph)
    path=tmp_path/'graph.json';path.write_text(json.dumps(graph),encoding='utf-8')
    manifest=tmp_path/'authority.json';manifest.write_text(json.dumps({'files':corpus.hashes}))
    return graph,SourceContextGraph(path,corpus.root,corpus_manifest=manifest,**options)


def test_parent_retrieval_returns_complete_original_with_real_edge_routes(tmp_path):
    text='# Topic\nparent context\n## Pressure\npressure fact\n## Impulse\nimpulse fact\n'
    graph,engine=fixture(tmp_path,{'manual/topic.md':text})
    result=engine.rank('pressure');packet=engine.read_native(result)
    assert packet['items'][0]['ranges']==[dict(start=1,end=6)]
    assert len(packet['items'])==1
    route_edges={e['id'] for e in graph['edges']}
    assert all(s['edge_id'] in route_edges for c in packet['items'][0]['context_fragments'] for s in c['route'])
    assert {c['owner'] for c in packet['items'][0]['context_fragments']}=={u['owner'] for u in graph['units'].values()}


@pytest.mark.parametrize('options',[{'options':{'with_cross':False}},{'options':{'with_paths':False}}])
def test_ablation_cannot_obtain_other_owners_through_parent_metadata(tmp_path,options):
    _,engine=fixture(tmp_path,{'manual/topic.md':'# Topic\nintro\n## Pressure\npressure\n## Impulse\nimpulse\n'},**options)
    packet=engine.read_native(engine.rank('pressure'))
    assert all(all(c['owner']==row['owner'] for c in row['context_fragments']) for row in packet['items'])


def test_budget_limits_parent_expansion_and_keeps_source_fields_unmodified(tmp_path):
    files={'manual/topic.md':'# Topic\n'+'parent prose\n'*100+'## Pressure\npressure fact\n'}
    graph,engine=fixture(tmp_path,files,context_characters=100)
    packet=engine.read_native(engine.rank('pressure'))
    first=packet['items'][0]
    assert first['ranges'][0]['start']>1
    assert len(first['context_fragments'])==1
    assert graph['source_context_revision']['questions_or_gold_used'] is False


def test_case_initialism_comes_from_arbitrary_source_path_and_filters_other_cases(tmp_path):
    assert 'DDT' in case_aliases('tutorials/solver/deflagrationToDetonationTransition')
    assert 'TPT' in case_aliases('tutorials/solver/thermalToPressureTransition')
    _,engine=fixture(tmp_path,{
        'tutorials/solver/thermalToPressureTransition/0/Su':'internalField uniform 0.2;',
        'tutorials/solver/otherCase/0/Su':'Su internalField uniform 0.9;',
        'tutorials/solver/thermalToPressureTransition/0/U':'internalField uniform 0.2;'})
    ranking=engine.rank('TPT 0/Su internalField')
    assert ranking['items'][0]['path'].endswith('thermalToPressureTransition/0/Su')
    assert all('/otherCase/' not in row['path'] for row in ranking['items'])


def test_parent_context_never_merges_files_with_same_heading(tmp_path):
    graph,engine=fixture(tmp_path,{'manual/a.md':'# Topic\npressure\n## Child\nvalue\n','manual/b.md':'# Topic\nunrelated\n'})
    for parent in graph['source_containers'].values():
        assert all(graph['units'][uid]['path']==parent['path'] for uid in parent['members'])
    packet=engine.read_native(engine.rank('pressure'))
    assert packet['items'][0]['path']=='manual/a.md'
    assert all(c['unit_id'] in graph['units'] for row in packet['items'] for c in row['context_fragments'])


def test_public_manual_scope_is_not_bypassed_by_filename_candidate_supplement(tmp_path):
    _,engine=fixture(tmp_path,{'manual/models.md':'# Models\nUse createBaffles and blockMeshDict.\n',
        'tutorials/solver/demo/system/blockMeshDict':'boundary inlet;\n'})
    result=engine.rank('只依据手册解释 createBaffles blockMeshDict')
    assert result['items'] and all(row['path'].startswith('manual/') for row in result['items'])


def test_unicode_identifier_selects_its_definition_before_incidental_mentions(tmp_path):
    _,engine=fixture(tmp_path,{'manual/models.md':'# Methods\n## Lohner\nScaled Laplacian.\n## Example\nLöhner is mentioned in this long example.\n'})
    result=engine.rank('Löhner 的定义')
    unit=engine.graph['units'][engine.nodes[result['items'][0]['node_id']]['unit_id']]
    assert unit['start']==2
    assert result['items'][0]['reasons']['direct_heading_identifiers']==['lohner']


def test_parent_literal_keys_corrobate_separately_owned_declarations(tmp_path):
    graph,engine=fixture(tmp_path,{'tutorials/demo/system/modes':'FoamFile\n{\n class dictionary;\n object modes;\n}\ntype hydrostatic;\nhydrostaticCoeffs\n{\n value 1;\n}\ntableCoeffs\n{\n value 2;\n}\n'})
    assert {'hydrostaticCoeffs','tableCoeffs'}<=set(graph['source_file_declarations']['tutorials/demo/system/modes']['keys'])
    result=engine.rank('hydrostaticCoeffs tableCoeffs')
    assert result['items'][0]['reasons']['parent_declaration_bonus']==12


def test_scenario_labels_are_not_physical_field_identifiers(tmp_path):
    _,engine=fixture(tmp_path,{'manual/models.md':'# Methods\n## Defaults\npartialBurst no by default. useDelta yes by default.\n## B\nB partialBurst example.\n'})
    result=engine.rank('场景 A：partialBurst 默认。场景 B：useDelta 默认。')
    first=result['items'][0]
    assert first['reasons']['original_identifier_overlap']==['partialburst','usedelta']


def test_parent_introduction_survives_when_full_parent_exceeds_context_allowance(tmp_path):
    _,engine=fixture(tmp_path,{'manual/models.md':'# Parent\nparent rules\n## Type\ntarget fact\n### Other\n'+'unrelated detail\n'*100},context_characters=150)
    packet=engine.read_native(engine.rank('target'))
    assert packet['items'][0]['ranges']==[dict(start=1,end=4)]
    assert source_case('tutorials/initializeAtmosphere/system/atmosphereProperties')=='tutorials/initializeAtmosphere'
