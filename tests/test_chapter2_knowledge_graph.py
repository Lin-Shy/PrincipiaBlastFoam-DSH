"""Mechanism tests: typed identity, ownership isolation and ablation invariants."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments/retrieval_method'))
from chapter2_graph_sources import prepare_sources
from chapter2_compile_knowledge_graph import compile_graph
from chapter2_knowledge_graph_retriever import KnowledgeGraphRetriever
from principia_core.retrieval.knowledge_qa import FrozenKnowledgeCorpus,KnowledgeToolSession,KnowledgeBudget
from chapter2_qa_backends import NativeBackend
from chapter2_knowledge_graph_variants import variant

def fixture(tmp_path):
    files={'manual/markdown/functions.md':'# overpressure\nA pressure function. It applies if enabled.\n',
      'manual/markdown/eos.md':'# overpressure\nA different EOS with the same public name.\n',
      'tutorials/blastFoam/case/system/controlDict':
       'FoamFile { format ascii; }\nfunctions\n{\n pressure\n {\n type overpressure;\n pRef 101325;\n }\n maximum\n {\n type fieldMinMax;\n pRef 5;\n }\n}\n'}
    rows=[]
    for name,text in files.items():
        p=tmp_path/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text,encoding='utf-8')
        rows.append({'path':name,'sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'bytes':len(p.read_bytes()),'lines':len(text.splitlines())})
    manifest=tmp_path/'manifest.json';manifest.write_text(json.dumps({'schema':'independent_blast_knowledge_corpus_v1','files':rows}))
    corpus=FrozenKnowledgeCorpus(tmp_path,manifest);source=prepare_sources(corpus);records=[]
    for u in source['units'].values():
        if not u['path'].startswith('manual/'):continue
        role='function_object' if 'functions.md' in u['path'] else 'equation_of_state'
        ev={'path':u['path'],'start':1,'end':2,'sha256':u['sha256'],'quote':u['text']}
        d={'id':'D1','name':'overpressure','role_category':role,'role':role,
           'body':'A pressure function.' if role=='function_object' else 'A different EOS.',
           'aliases':[],'conditions':['if enabled'] if role=='function_object' else [],
           'input_signature':[],'output_signature':[],'identity_selectors':{},'evidence':[ev]}
        records.append({'unit_id':u['id'],'accepted':{'definitions':[d],'facts':[],'relations':[],'rejected':[]}})
    graph=compile_graph(source,records,corpus.hashes,complete=True,binding={})
    path=tmp_path/'graph.json';path.write_text(json.dumps(graph))
    authority=tmp_path/'authority.json';authority.write_text(json.dumps({'files':corpus.hashes}))
    def engine(**options):return KnowledgeGraphRetriever(path,tmp_path,options,authority)
    return graph,path,corpus,engine

def test_same_name_requires_typed_role_and_parameter_namespace(tmp_path):
    graph,path,corpus,engine=fixture(tmp_path);nodes=graph['nodes']
    selected=next(n for n in nodes.values() if n.get('dictionary')=='functions/pressure/type')
    links=[e for e in graph['edges'] if e['source']==selected['id'] and e['relation']=='DOCUMENTED_BY']
    assert len(links)==1 and nodes[links[0]['target']]['role_category']=='function_object'
    param=next(n for n in nodes.values() if n.get('dictionary')=='functions/pressure/pRef')
    contexts=[e for e in graph['edges'] if e['source']==param['id'] and e['relation']=='PARAMETER_CONTEXT']
    assert {e['target'] for e in contexts}=={selected['id']}
    assert not any(e['source']==param['id'] and nodes[e['target']].get('dictionary')=='functions/maximum/type' for e in graph['edges'])

def test_no_cross_removes_every_owner_boundary_and_no_shared_node_bridge(tmp_path):
    graph,path,corpus,engine=fixture(tmp_path)
    full=engine();removed=engine(with_cross=False)
    assert full.owner_boundary_audit()['maximum_owners_per_component']>1
    audit=removed.owner_boundary_audit()
    assert audit['maximum_owners_per_component']==1 and audit['nodes']==len(graph['nodes'])
    assert audit['cross_owner_edges_retained']==0
    # Flat matching is still allowed to find more than one source independently.
    assert len({r['owner'] for r in removed.rank('overpressure')['items']})>1
    assert all(not edge['cross_owner'] for r in removed.rank('overpressure')['items'] for edge in r['route'])

def test_ablation_keeps_seeds_sources_and_raw_content_and_only_disables_paths(tmp_path):
    graph,path,corpus,engine=fixture(tmp_path);full=engine().rank('overpressure enabled')
    flat=engine(with_paths=False).rank('overpressure enabled')
    assert full['diagnostic']['seeds']==flat['diagnostic']['seeds']
    assert flat['diagnostic']['expanded_edges']==0 and all(not r['route'] for r in flat['items'])
    bare=engine(with_conditions=False).rank('overpressure enabled')
    assert all(r['conditions']==[] for r in bare['items'])
    assert all(e['conditions']==[] for r in bare['items'] for e in r['route'])
    assert all(r['reasons'].get('condition_overlap',0)==0 for r in bare['diagnostic']['seeds'])
    strip=lambda n:{k:v for k,v in n.items() if k!='conditions'}
    assert {nid:strip(n) for nid,n in engine().nodes.items()}==engine(with_conditions=False).nodes
    assert corpus.lines('manual/markdown/functions.md')[1].endswith('if enabled.')

def test_graph_packets_use_actual_raw_delivery_and_common_budgets(tmp_path):
    graph,path,corpus,engine=fixture(tmp_path)
    tools=KnowledgeToolSession('graph',corpus,NativeBackend(engine(),graph=True),KnowledgeBudget(tool_calls=2,tool_characters=1200,total_characters=1600))
    delivered=json.loads(tools.execute('search',{'query':'overpressure'}))
    assert tools.characters<=1200 and delivered['evidence']
    for row in delivered['evidence']:
        assert row['lines']==corpus.read(row['path'],row['start'],row['end'])['lines']
        assert 'body' not in row and 'conditions' not in row

def test_unowned_nodes_and_changed_raw_sources_are_rejected(tmp_path):
    graph,path,corpus,engine=fixture(tmp_path)
    first=next(iter(graph['nodes']));graph['nodes'][first]['owner']='global shared entity'
    path.write_text(json.dumps(graph))
    with pytest.raises(ValueError,match='shared'):engine()
    graph['nodes'][first]['owner']=graph['units'][graph['nodes'][first]['unit_id']]['owner'];path.write_text(json.dumps(graph))
    p=tmp_path/'manual/markdown/functions.md';p.write_text('different text')
    with pytest.raises(ValueError,match='source changed'):engine()

def test_materialized_variants_preserve_facts_and_have_no_ablation_bypass(tmp_path):
    graph,path,corpus,engine=fixture(tmp_path)
    no_cross,audit=variant(graph,'no_cross');path.write_text(json.dumps(no_cross))
    assert audit['cross_owner_edges_after']==0 and engine(with_cross=False).owner_boundary_audit()['maximum_owners_per_component']==1
    no_cond,audit=variant(graph,'no_conditions');path.write_text(json.dumps(no_cond))
    assert audit['condition_fields_after']==0 and audit['condition_edges_after']==0
    assert all('conditions' not in n for n in engine(with_conditions=False).nodes.values())
    flat,audit=variant(graph,'no_extension');path.write_text(json.dumps(flat))
    assert flat['edges']==[] and engine(with_paths=False).rank('overpressure')['diagnostic']['expanded_edges']==0
    with pytest.raises(ValueError,match='ablation disagree'):engine()
