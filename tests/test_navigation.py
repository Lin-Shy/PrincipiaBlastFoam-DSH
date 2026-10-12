from pathlib import Path
import sys
from types import SimpleNamespace
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'.dsh/skills/blastfoam-knowledge/scripts'))
import global_graph as g
from navigate import Navigator,bounded,tokens
from context_packets import wire


@pytest.fixture
def nav(tmp_path):
    corpus=tmp_path/'corpus';(corpus/'manual').mkdir(parents=True)
    (corpus/'manual/page.txt').write_text(''.join(f'line {i} contains source evidence\n' for i in range(60)))
    entities=[{'kind':'model','namespace':n,'name':'single'} for n in ['pressure','velocity']]
    entities+=[{'kind':'parameter','namespace':'velocity','name':'phase'}]
    ids=[g.entity_id(e) for e in entities]
    cards={'card:a':{'id':'card:a','scope':'manual','case':None,'title':'model','relation':'DESCRIBES','entities':[entities[1],entities[2]],
                      'evidence':[{'path':'manual/page.txt','line_start':2,'line_end':4}]},
           'card:b':{'id':'card:b','scope':'manual','case':None,'title':'other','relation':'DEFINES_PARAMETER','entities':[entities[0]],
                      'evidence':[{'path':'manual/page.txt','line_start':6,'line_end':8}]}}
    graph=SimpleNamespace(skill=tmp_path,graph={'snapshot':'test'},cards=cards,entities=dict(zip(ids,entities)),
            manifest={'case_paths':['tutorials/a','tutorials/b'],'corpus_hashes':g.inventory(tmp_path)},
            adj={ids[0]:[{'target':'card:b'}],ids[1]:[{'target':'card:a'}],ids[2]:[{'target':'card:a'}]})
    return Navigator(graph)


def test_discovery_preserves_identity_and_requires_actual_ids(nav):
    result=nav.discover('single');assert len(result['items'])==2
    assert len({x['id'] for x in result['items']})==2
    with pytest.raises(ValueError,match='unknown entity'):nav.inspect('single')
    assert nav.discover('nonexistent')['items']==[]


def test_browsing_exposes_actual_relations_without_hard_filter(nav):
    entity=nav.discover('velocity',kind='model')['items'][0]
    r=nav.inspect(entity['id']);assert r['relations']=={'DESCRIBES':1}
    assert r['items'][0]['sources'][0]['path']=='manual/page.txt'


def test_neighbor_routes_are_explicit_comembership_not_inferred_dependencies(nav):
    entity=nav.discover('velocity',kind='model')['items'][0]
    r=nav.neighbors(entity['id']);assert r['items'][0]['name']=='phase'
    assert r['items'][0]['via_cards']==['card:a']
    assert 'not a causal' in r['interpretation']
    with pytest.raises(ValueError):nav.neighbors(entity['id'],'card:b')


def test_source_pagination_is_lossless_and_budgeted(nav):
    outputs=[];start=1
    while start:
        result=nav.source('manual/page.txt',start,budget=600)
        assert len(wire(result))<=600 and result['text']
        outputs.append(result['text']);start=result['next_line']
    assert ''.join(outputs)==(nav.g.skill/'corpus/manual/page.txt').read_text()


def test_source_rejects_path_escape_and_changed_content(nav):
    with pytest.raises(ValueError,match='outside corpus'):nav.source('../secret')
    (nav.g.skill/'corpus/manual/page.txt').write_text('edited')
    with pytest.raises(ValueError,match='source changed'):nav.source('manual/page.txt')


def test_pagination_never_silently_skips_oversized_item():
    r=bounded({'status':'ok'},[{'text':'x'*800},{'text':'small'}],budget=256)
    assert r['next_offset']==0 and r['status']=='budget_too_small_for_first_item'
    assert not r['items']


def test_case_and_source_scope_checks(nav):
    with pytest.raises(ValueError,match='case_unavailable'):Navigator(nav.g,case='tutorials/missing')
    n=Navigator(nav.g,scope='tutorial')
    assert n.discover()['items']==[]
    with pytest.raises(ValueError,match='tutorial scope'):n.source('manual/page.txt')


def test_read_beyond_eof_returns_available_lines_but_bad_start_is_rejected(nav):
    r=nav.source('manual/page.txt',start=58,end=200,budget=1000)
    assert r['line_end']==60 and r['total_lines']==60 and r['next_line'] is None
    assert r['requested_end']==200
    with pytest.raises(ValueError,match='60 lines'):nav.source('manual/page.txt',start=61)


def test_unknown_kind_is_not_misreported_as_absent_evidence(nav):
    with pytest.raises(ValueError,match='invalid kind'):nav.discover('single',kind='directory')
    r=nav.discover('nothing',kind='file')
    assert r['available_kinds']==['model','parameter'] and r['items']==[]
