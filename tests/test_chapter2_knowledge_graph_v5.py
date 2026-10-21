"""Source ownership, directed literal links and query-gated context invariants."""
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments/retrieval_method'))
from test_chapter2_graph_source_context import fixture
from chapter2_build_graph_v5 import augment
from chapter2_knowledge_graph_v5 import FocusedEvidenceGraph

def make(tmp_path, files, policy='balanced'):
    graph,previous=fixture(tmp_path,files)
    augmented=augment(graph)
    p=tmp_path/'augmented.json';p.write_text(json.dumps(augmented),encoding='utf-8')
    return graph,augmented,FocusedEvidenceGraph(p,previous.root,corpus_manifest=tmp_path/'authority.json',policy=policy)

def test_literal_reference_retains_both_original_source_anchors_and_direction(tmp_path):
    old,g,engine=make(tmp_path,{'manual/models.md':'# Models\n## GammaLaw\nA named model.\n',
        'tutorials/demo/constant/properties':'FoamFile\n{\n class dictionary;\n object properties;\n}\nequationOfState GammaLaw;\n'})
    edges=[e for e in g['edges'] if e['relation']=='LITERAL_HEADING_REFERENCE']
    assert len(edges)==1
    edge=edges[0]
    assert edge['cross_file'] and edge['support']['literal']=='GammaLaw'
    assert g['nodes'][edge['source']]['kind']=='configuration'
    assert g['nodes'][edge['target']]['kind']=='literal_heading'
    assert g['units']==old['units'] and g['source_hashes']==old['source_hashes']
    packet=engine.read_native(engine.rank('equationOfState GammaLaw'))
    assert packet['items']
    for row in packet['items']:
        assert row['original_sha256']==engine.hashes[row['path']]

def test_ambiguous_and_generic_headings_do_not_create_identity_bridges(tmp_path):
    _,g,_=make(tmp_path,{'manual/a.md':'# Models\n## GammaLaw\nfirst namespace\n## none\nno model\n',
        'manual/b.md':'# Other\n## GammaLaw\nsecond namespace\n',
        'tutorials/demo/constant/properties':'FoamFile\n{\n class dictionary;\n object properties;\n}\nequationOfState GammaLaw;\nactivationModel none;\n'})
    assert not [e for e in g['edges'] if e['relation']=='LITERAL_HEADING_REFERENCE']
    assert g['literal_heading_revision']['ambiguous_references_not_linked']

def test_gated_context_does_not_include_an_unrequested_sibling(tmp_path):
    _,g,engine=make(tmp_path,{'manual/models.md':'# Models\nintroduction\n## PressureSolver\npressure detail\n## UnrelatedHeat\nunrelated thermal detail\n'},policy='gated')
    ranking=engine.rank('PressureSolver')
    # Limit to the explicitly located unit to distinguish physical expansion
    # from a later independent candidate in the retrieval ranking.
    located=next(r for r in ranking['items'] if g['units'][g['nodes'][r['node_id']]['unit_id']]['start']==3)
    packet=engine.read_native({**ranking,'items':[located]})
    assert all(span['end']<5 for row in packet['items'] for span in row['ranges'])

def test_normalized_walk_and_ranking_are_deterministic_and_no_external_index(tmp_path):
    _,_,engine=make(tmp_path,{'manual/models.md':'# Models\n## GammaLaw\npressure equation\n',
        'tutorials/demo/constant/properties':'FoamFile\n{\n class dictionary;\n object properties;\n}\nequationOfState GammaLaw;\n'},policy='ppr')
    a=engine.rank('GammaLaw pressure');b=engine.rank('GammaLaw pressure')
    assert [(r['node_id'],r['selection_score']) for r in a['items']]==[(r['node_id'],r['selection_score']) for r in b['items']]
    assert a['diagnostic']['external_index_loaded'] is False
    assert a['diagnostic']['question_or_result_cache'] is False

def test_literal_lookup_cannot_bypass_an_explicit_tutorial_only_scope(tmp_path):
    _,_,engine=make(tmp_path,{'manual/models.md':'# Models\n## GammaLaw\npressure equation\n',
        'tutorials/demo/constant/properties':'FoamFile\n{\n class dictionary;\n object properties;\n}\nequationOfState GammaLaw;\n'})
    ranking=engine.rank('仅查教程 equationOfState GammaLaw')
    assert ranking['items']
    assert all(row['path'].startswith('tutorials/') for row in ranking['items'])

def test_budget_policy_changes_only_context_not_frozen_nodes_or_ranked_seeds(tmp_path):
    _,graph,engine=make(tmp_path,{'manual/models.md':'# Models\n## GammaLaw\npressure equation\n'},policy='adaptive')
    before=json.dumps(engine.graph,sort_keys=True)
    ranking=engine.rank('GammaLaw')
    small=engine.read_for_budget(ranking,6000)
    large=engine.read_for_budget(ranking,24000)
    assert small['items'] and large['items']
    assert json.dumps(engine.graph,sort_keys=True)==before
    assert engine.context_characters==1200
