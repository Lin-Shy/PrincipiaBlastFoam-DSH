"""真实语料/合成边界测试；无LLM、无评分数据。"""
import json
import subprocess
import sys
from pathlib import Path

import pytest
from common import *
from text_baselines import BM25,RRF,ParentBM25,hierarchy_ranges
from retrieval import canonical_ranges,SlotsBackend
from principia_core.retrieval.knowledge_qa import FrozenKnowledgeCorpus,KnowledgeToolSession,KnowledgeBudget

@pytest.fixture(scope='module')
def corpus():return FrozenKnowledgeCorpus(RESOURCES/'corpus',RESOURCES/'corpus-manifest.json')

@pytest.fixture(scope='module')
def bm25():return BM25()

@pytest.fixture(scope='module')
def graph():
    from graph_ablations import create_graph
    return create_graph()

def test_bm25_exact_historical_ranking(bm25):
    from chapter2_baseline_native import NoGraphBM25
    old=NoGraphBM25(RESOURCES/'corpus',RESOURCES/'source-map.json')
    for query in ['fieldValue delta pressure','What is the default flux scheme?', 'AMR误差怎么定义？']:
        packet,_=old.query(query,{},64)
        expected=[(r['path'],r['start'],r['end'],r['score']) for r in packet['items']]
        actual=[(r['path'],r['start'],r['end'],r['score']) for r in bm25.rank(query)]
        assert actual==expected
        assert bm25.rank(query)==bm25.rank(query)

def test_dedup_multiple_overlapping_ranges():
    rows=[dict(path='a',start=1,end=5),dict(path='a',start=3,end=8),dict(path='b',start=1,end=3),dict(path='a',start=1,end=8)]
    out=canonical_ranges(rows)
    ledger=[(r['path'],n) for r in out for n in range(r['start'],r['end']+1)]
    assert len(ledger)==len(set(ledger))==11

def test_rrf_deterministic_duplicate_ranges():
    class Rank:
        def rank(self,q,limit):return [dict(path='a',start=1,end=2),dict(path='a',start=1,end=2),dict(path='b',start=1,end=2)]
    engine=RRF(Rank(),Rank());rows=engine.rank('q')
    assert rows[0]['score']==2/61
    assert len(rows)==2 and rows==engine.rank('q')
    assert engine.last_trace['k']==60

@pytest.mark.parametrize('cap',[1,50,2000,4000,6000])
def test_serialized_budget_and_source_lines(corpus,bm25,cap):
    rows=bm25.rank('fieldValue')[:10]
    tools=KnowledgeToolSession('bm25',corpus,SlotsBackend(rows),KnowledgeBudget(1,cap,cap))
    response=tools.execute('search',{'query':'fieldValue'})
    assert len(response)<=cap
    if response:
        packet=json.loads(response)
        for evidence in packet.get('evidence',[]):
            lines=corpus.lines(evidence['path'])
            assert evidence['sha256']==corpus.hashes[evidence['path']]
            for line in evidence['lines']:assert lines[line['number']-1]==line['text']
    ledger=tools.events[0]['delivered_original_lines']
    assert len(ledger)==len({(r['path'],r['line']) for r in ledger})

def test_source_drift_fail_closed(tmp_path):
    from chapter2_baseline_native import OriginalSources
    source=tmp_path/'a';source.write_text('first\n',encoding='utf-8')
    manifest=tmp_path/'manifest.json';manifest.write_text(json.dumps({'files':{'a':sha(source)}}))
    engine=OriginalSources(tmp_path,manifest)
    assert engine.read('a',{})==['first']
    source.write_text('changed\n',encoding='utf-8')
    with pytest.raises(ValueError):engine.read('a',{})

def test_independent_parser_and_context(bm25):
    lines=['# Outer','intro','## Inner','a','```','# Not a heading','```','## Next','end']
    parents=hierarchy_ranges(lines)
    assert (3,7,'markdown_section') in parents
    assert not any(a==6 for a,b,k in parents)
    rows=ParentBM25(bm25).rank('fieldValue')
    assert rows[0]['delivery_role']=='anchor'
    for row in rows:
        if row.get('delivery_role')=='context':assert row['added_characters']<=1200

def normalized_ranking(ranking):
    return [(r['node_id'],r['score'],r['native_rank'],r['route']) for r in ranking['items']]

def test_full_graph_exact_original_and_independent_switches(graph):
    from graph_ablations import create_graph,full_slots,anchor_slots
    from chapter2_knowledge_graph_v6 import BilingualScopeGraph
    old=BilingualScopeGraph(GRAPH,corpus=RESOURCES/'corpus',corpus_manifest=RESOURCES/'source-map.json',
        options=dict(with_conditions=False,with_cross=True,with_paths=True),semantic_policy='unit')
    no=create_graph(False)
    for query in ['fieldValue delta pressure','blastFoam fluxScheme HLLC']:
        rank=graph.rank(query);ref=old.rank(query)
        assert normalized_ranking(rank)==normalized_ranking(ref)
        a=graph.read_native(rank);b=old.read_native(ref)
        assert a['items']==b['items']
        nr=no.rank(query)
        assert nr['diagnostic']['expanded_edges']==0
        assert all(not row['route'] for row in nr['items'])
        assert no.options['with_paths'] is True
        assert no._facet_flat(query)['items']==graph.initial_flat(query)['items']
        # Context calculation is identical for an identical located node, even
        # when the ablated ranking places different nodes in its top10.
        hits={graph.nodes[r['node_id']]['unit_id'] for r in rank['items'][:10]}
        assert no._select_context(rank['items'][0],hits)==graph._select_context(rank['items'][0],hits)
        packet,slots=full_slots(graph,rank)
        anchors=anchor_slots(graph,rank,slots)
        assert len({r['node_id'] for r in anchors})<=len({r['node_id'] for r in slots})
        for row in anchors:
            assert any(e['start']<=row['start']<=row['end']<=e['end'] for e in graph.nodes[row['node_id']]['evidence'])
        assert normalized_ranking(rank)==normalized_ranking(graph.rank(query))

def test_guard_blocks_gold_graph_and_network_for_text():
    code='''
import sys
from pathlib import Path
from common import *
from retrieval import install_guard
opened=install_guard()
def deny_graph(event,args):
 if event=='open' and args and isinstance(args[0],(str,bytes)) and str(args[0]).replace('\\\\','/').endswith('/selected.json'):
  raise PermissionError('text must not open graph')
sys.addaudithook(deny_graph)
from text_baselines import BM25,ParentBM25
assert ParentBM25(BM25()).rank('fieldValue')
for f in [DATASET/'scoring/annotations.json',DATASET/'scoring/evidence.json']:
 try:f.read_bytes();raise AssertionError('gold was readable')
 except PermissionError:pass
import socket
try:socket.create_connection(('example.com',443),timeout=1);raise AssertionError('network allowed')
except PermissionError:pass
'''
    result=subprocess.run([sys.executable,'-X','utf8','-c',code],cwd=HERE,capture_output=True,text=True,encoding='utf-8')
    assert result.returncode==0,result.stderr

def test_bge_implementation_has_only_dense_channels():
    # Real weight/inference verification is recorded separately after download.
    import ast
    tree=ast.parse((HERE/'bge_m3_dense.py').read_text(encoding='utf-8'))
    imports=[n.module for n in ast.walk(tree) if isinstance(n,ast.ImportFrom)]
    assert 'FlagEmbedding' not in imports
    assert 'transformers' in imports
