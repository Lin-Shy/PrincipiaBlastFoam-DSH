import json
from test_chapter2_graph_sources import corpus as make_corpus
from chapter2_graph_sources import prepare_sources
from chapter2_compile_knowledge_graph import compile_graph
from chapter2_graph_selector_context import add_file_selectors
from chapter2_knowledge_graph_v2 import EvidenceGraphV2


def fixture(tmp_path):
    raw='FoamFile { format ascii; }\ntype hydrostatic;\nhydrostaticCoeffs { hRef -10; }\ntableCoeffs { correct false; }\n'
    corpus=make_corpus(tmp_path,{'tutorials/initializeAtmosphere/system/atmosphereProperties':raw})
    graph=compile_graph(prepare_sources(corpus),[],corpus.hashes,complete=True,binding={})
    revised=add_file_selectors(graph)
    path=tmp_path/'graph.json';path.write_text(json.dumps(revised))
    authority=tmp_path/'authority.json';authority.write_text(json.dumps({'files':corpus.hashes}))
    return graph,revised,path,authority,corpus


def test_unique_file_selector_is_source_owned_context_and_preserves_original_nodes(tmp_path):
    graph,revised,path,authority,corpus=fixture(tmp_path)
    assert revised['nodes']==graph['nodes']
    edges=[e for e in revised['edges'] if e['relation']=='FILE_SELECTOR_CONTEXT']
    assert edges
    for edge in edges:
        a,b=revised['nodes'][edge['source']],revised['nodes'][edge['target']]
        assert a['path']==b['path'] and b['components']==['type'] and b['value']=='hydrostatic'
        assert edge['status']=='literal_file_context_not_effective_runtime_selection'
    engine=EvidenceGraphV2(path,corpus.root,corpus_manifest=authority)
    rows=engine.rank('tableCoeffs correct')['items']
    assert any(revised['nodes'][r['node_id']].get('key')=='type' for r in rows)
    assert all(step['direction']=='forward' for row in rows for step in row['route'] if step['relation']=='FILE_SELECTOR_CONTEXT')


def test_selector_context_cannot_bypass_no_cross_owner_ablation(tmp_path):
    graph,revised,path,authority,corpus=fixture(tmp_path)
    engine=EvidenceGraphV2(path,corpus.root,options={'with_cross':False},corpus_manifest=authority)
    assert engine.owner_boundary_audit()['cross_owner_edges_retained']==0
    assert all(not step['cross_owner'] for row in engine.rank('tableCoeffs correct')['items'] for step in row['route'])


def test_ambiguous_top_level_selector_does_not_get_an_arbitrary_choice(tmp_path):
    graph,revised,path,authority,corpus=fixture(tmp_path)
    selector=next(n for n in graph['nodes'].values() if n.get('components')==['type'])
    graph['nodes']['other-literal']={**selector,'id':'other-literal','value':'table'}
    revised=add_file_selectors(graph)
    assert not any(e['relation']=='FILE_SELECTOR_CONTEXT' for e in revised['edges'])
    assert revised['selector_context_revision']['ambiguous_selectors_unlinked']
