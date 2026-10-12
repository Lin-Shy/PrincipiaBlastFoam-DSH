import importlib.util
from pathlib import Path
import sys
import json
from collections import defaultdict

import pytest

SKILL=Path(__file__).resolve().parents[1]/'.dsh/skills/blastfoam-knowledge'
sys.path.insert(0,str(SKILL/'scripts'))
import global_graph as g
import context_packets as p


def test_only_exact_flash_name_is_allowed_for_global_extraction():
    with pytest.raises(ValueError,match='requires deepseek-flash'):
        g.make_plan(model='other-model')


def test_source_blocks_preserve_all_text_and_line_numbers():
    text='first\nsecond\nthird\n'
    blocks=list(g.source_blocks('x',text,'hash',maximum=9))
    assert ''.join(b['text'] for b in blocks)==text
    assert [b['line_start'] for b in blocks]==[1,2,3]
    assert g.locate_quote(blocks[1],'second')['line_start']==2


def test_quotes_require_exact_unique_source_content():
    block={'path':'x','sha256':'hash','line_start':4,'text':'alpha beta\ngamma beta\n','pdf_page':None}
    assert g.locate_quote(block,'alpha\nbeta')['quote']=='alpha beta'
    for quote in ('beta','invented quote','ALPHA beta'):
        with pytest.raises(ValueError):g.locate_quote(block,quote)


def test_entity_identity_keeps_namespace_and_near_names_separate():
    ids={g.entity_id({'kind':'model','namespace':ns,'name':name}) for ns,name in
         [('EOS','JWL'),('EOS','solidJWL'),('activationModel','JWL')]}
    assert len(ids)==3
    graph=object.__new__(g.GlobalGraph)
    a={'kind':'model','namespace':'EOS','name':'JWL'};b={**a,'name':'solidJWL'}
    graph.entities={g.entity_id(a):a,g.entity_id(b):b};graph.adj=defaultdict(list)
    graph.cards={};graph.graph={'snapshot':'test','limits':[]}
    result=graph.lookup(['JWL'])
    assert result['matched_entity_count']==1


def test_deleted_unit_cache_cannot_reappear_in_assembly(tmp_path,monkeypatch):
    corpus=tmp_path/'corpus';corpus.mkdir();(corpus/'current.txt').write_text('current')
    cache=tmp_path/'semantic/global/cache';cache.mkdir(parents=True)
    (cache/'unused.json').write_text(json.dumps({'status':'ok','payload':{'cards':[{'id':'obsolete'}]}}))
    plan={'units':[],'resources':[],'case_paths':[],'corpus_hashes':g.inventory(tmp_path),
          'extraction':{'model':'deepseek-flash'},'structure_snapshot':'fixed'}
    manifest=g.assemble(plan,tmp_path)
    assert manifest['counts']['cards']==0
    assert g.GlobalGraph(tmp_path).graph['cards']==[]
    (corpus/'current.txt').write_text('changed')
    with pytest.raises(ValueError,match='source changes'):g.GlobalGraph(tmp_path)


def test_model_mismatch_cannot_publish(tmp_path):
    cache=tmp_path/'semantic/global/cache';cache.mkdir(parents=True)
    g.write(cache/'key.json',{'status':'ok','cache_key':'key','model':'other-model'})
    with pytest.raises(ValueError,match='model/cache mismatch'):
        g.assemble({'units':[{'id':'u','cache_key':'key'}],'extraction':{'model':'deepseek-flash'}},tmp_path)
    assert not (tmp_path/'semantic/global/current.json').exists()


def test_character_budget_includes_metadata_and_preserves_whole_items(tmp_path):
    text='line one\n'+('中文内容'*250)+'\nlast line\n';(tmp_path/'x').write_text(text)
    ev={'path':'x','line_start':1,'line_end':3}
    item=p.source_item(tmp_path,ev,metadata={'relation':'DESCRIBES','condition':'unknown'})
    packet=p.pack([item],2000)
    assert len(p.wire(packet))<=2000
    assert len(p.wire(packet))>len(item['text'])
    short=p.pack([item],256)
    assert not short['evidence'] and short['status']=='budget_too_small_for_first_item'
    with pytest.raises(ValueError):p.source_item(tmp_path,{**ev,'line_start':99,'line_end':99})
    with pytest.raises(ValueError):p.source_item(tmp_path,{**ev,'path':'../outside'})


def test_span_metrics_distinguish_same_file_from_actual_support(tmp_path):
    (tmp_path/'x').write_text('unrelated first\nrequired evidence\ntrailing\n')
    annotation={'answerability':'supported','evidence':[{'path':'x','line_start':2,'line_end':2,'quote':'required evidence'}]}
    wrong=p.source_item(tmp_path,{'path':'x','line_start':1,'line_end':1})
    right=p.source_item(tmp_path,{'path':'x','line_start':2,'line_end':2})
    result=p.measure(p.pack([wrong],2000),annotation,tmp_path)
    assert result['seed_path_recall']==1 and result['seed_span_recall']==0
    result=p.measure(p.pack([wrong,right],2000),annotation,tmp_path)
    assert result['all_seed_spans_covered'] and result['first_seed_reciprocal_rank']==.5
    assert 0<result['marked_evidence_character_fraction']<1


def test_overlapping_source_windows_measure_redundancy(tmp_path):
    (tmp_path/'x').write_text('a first\nb second\nc third\n')
    a=p.source_item(tmp_path,{'path':'x','line_start':1,'line_end':2})
    b=p.source_item(tmp_path,{'path':'x','line_start':2,'line_end':3})
    annotation={'answerability':'supported','evidence':[{'path':'x','line_start':2,'line_end':2,'quote':'b second'}]}
    result=p.measure(p.pack([a,b],2000),annotation,tmp_path)
    assert result['seed_span_recall']==1
    assert result['duplicate_source_character_fraction']>0
    assert len(p.pack([a,a],2000)['evidence'])==1
