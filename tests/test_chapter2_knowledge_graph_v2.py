import json
import pytest
from test_chapter2_knowledge_graph import fixture
from chapter2_knowledge_graph_v2 import EvidenceGraphV2
from chapter2_build_graph_v2 import add_source_hierarchy
from test_chapter2_graph_sources import corpus as make_corpus
from chapter2_graph_sources import prepare_sources
from chapter2_compile_knowledge_graph import compile_graph


def test_typed_route_keeps_parameter_documentation_without_structural_hub_bonus(tmp_path):
    graph, path, corpus, _ = fixture(tmp_path)
    engine = EvidenceGraphV2(path, corpus.root, corpus_manifest=tmp_path/'authority.json')
    result = engine.rank('functions/pressure/pRef')
    assert result['diagnostic']['cross_owner_additive_bonus'] == 0
    assert len({engine.nodes[r['node_id']]['unit_id'] for r in result['items']}) == len(result['items'])
    assert all(step['relation'] not in {'HAS_ENTRY', 'HAS_LITERAL', 'GROUNDED_IN'} for r in result['items'] for step in r['route'])
    assert any(row['path'] == 'manual/markdown/functions.md' for row in result['items'])
    assert engine.options['with_paths'] is True


def test_compact_delivery_contains_only_authoritative_original_ranges(tmp_path):
    graph, path, corpus, _ = fixture(tmp_path)
    engine = EvidenceGraphV2(path, corpus.root, corpus_manifest=tmp_path/'authority.json')
    packet = engine.read_native(engine.rank('overpressure'))
    for row in packet['items']:
        node = engine.nodes[row['native_unit']]
        unit = graph['units'][node['unit_id']]
        assert row['owner'] == unit['owner']
        for span in row['ranges']:
            assert unit['start'] <= span['start'] <= span['end'] <= unit['end']
            assert corpus.read(row['path'], span['start'], span['end'])['lines']


def test_ablations_still_block_all_owner_boundaries_and_condition_fields(tmp_path):
    graph, path, corpus, _ = fixture(tmp_path)
    engine = EvidenceGraphV2(path, corpus.root, options={'with_cross':False, 'with_conditions':False}, corpus_manifest=tmp_path/'authority.json')
    result = engine.rank('overpressure enabled')
    assert all(not step['cross_owner'] and not step['conditions'] for r in result['items'] for step in r['route'])
    assert all(not r['conditions'] for r in result['items'])


def test_source_hierarchy_is_structural_and_cannot_cross_files(tmp_path):
    graph, path, corpus, _ = fixture(tmp_path)
    # The fixture has no nested headings; it must not invent connections from
    # a shared public name or a matching basename in a different file.
    revised = add_source_hierarchy(graph)
    assert revised['development_revision']['added_heading_edges'] == 0
    assert revised['development_revision']['questions_or_gold_used'] is False
    assert graph['nodes'] == revised['nodes']


def test_nested_original_heading_links_are_literal_and_owner_labelled(tmp_path):
    corpus=make_corpus(tmp_path,{'manual/markdown/nested.md':'# Models\nintro\n## Alpha\nalpha\n### Detail\ndetail\n## Beta\nbeta\n'})
    source=prepare_sources(corpus)
    graph=compile_graph(source,[],corpus.hashes,complete=True,binding={})
    revised=add_source_hierarchy(graph)
    edges=[e for e in revised['edges'] if e['relation']=='SOURCE_SECTION_PARENT']
    assert {(e['support']['child_start'],e['support']['parent_heading_line']) for e in edges}=={(3,1),(5,3),(7,1)}
    assert all(e['cross_owner'] and not e['cross_file'] for e in edges)
    assert graph['edges']==[]


def test_compact_quote_in_long_unit_retains_scope_and_can_be_continued(tmp_path):
    text='# Alpha\n'+'generic original source line\n'*80+'specialSetting true;\n'+'generic original source line\n'*30
    corpus=make_corpus(tmp_path,{'manual/markdown/long.md':text})
    source=prepare_sources(corpus);graph=compile_graph(source,[],corpus.hashes,complete=True,binding={})
    unit=next(iter(graph['units'].values()));nid='source-owned-fact'
    graph['nodes'][nid]=dict(id=nid,unit_id=unit['id'],owner=unit['owner'],path=unit['path'],
        kind='domain_fact',label='specialSetting',aliases=[],conditions=[],
        evidence=[dict(path=unit['path'],sha256=unit['sha256'],start=82,end=82)])
    path=tmp_path/'graph.json';path.write_text(json.dumps(graph))
    authority=tmp_path/'authority.json';authority.write_text(json.dumps({'files':corpus.hashes}))
    engine=EvidenceGraphV2(path,corpus.root,corpus_manifest=authority)
    packet=engine.read_native(dict(items=[dict(node_id=nid,native_rank=1,owner=unit['owner'])],diagnostic={}))
    assert packet['items'][0]['ranges']==[dict(start=78,end=86)]
    assert packet['items'][0]['owning_original_fragment']['end']>86


def test_platform_name_and_contents_do_not_outvote_specific_source_identity(tmp_path):
    files={'manual/markdown/topics.md':'# Contents\nblastFoam pressureAndImpulse burst patch\n# Burst patches\n## pressureAndImpulse\nCombines pressure and impulse.\n',
        'manual/markdown/intro.md':'# blastFoam\nblastFoam is an OpenFOAM toolbox.\n'}
    corpus=make_corpus(tmp_path,files);source=prepare_sources(corpus)
    graph=compile_graph(source,[],corpus.hashes,complete=True,binding={})
    path=tmp_path/'graph.json';path.write_text(json.dumps(graph))
    authority=tmp_path/'authority.json';authority.write_text(json.dumps({'files':corpus.hashes}))
    engine=EvidenceGraphV2(path,corpus.root,corpus_manifest=authority)
    result=engine.rank('blastFoam burst pressureAndImpulse')
    first=engine.nodes[result['items'][0]['node_id']]
    assert graph['units'][first['unit_id']]['start']==4
    assert result['diagnostic']['navigation_only_nodes_excluded']>0
    assert all('blast' not in r['reasons'].get('technical_identifier_overlap',[]) for r in result['diagnostic']['seeds'])
