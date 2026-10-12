"""Review gating, provenance, explicit scope and reverse-navigation regressions."""
from test_evidence_bundle import engine
import copy
import pytest
import domain_graph as d
import evidence_bundle as b
from locate import locate


def semantic_fixture(engine):
    foundation=d.m.build(engine.skill/'corpus/manual/markdown')
    node=next(n for n in foundation['nodes'] if n['kind']=='evidence' and 'The sampled quantity' in n['markdown'])
    subject={'id':'subject','kind':'model','name':'sampling','scope':node['section']}
    obj={'id':'object','kind':'parameter','name':'fields','scope':node['section']}
    f={'id':'fact:fixture','subject':subject,'object':obj,'section':node['section'],
       'relation':'REQUIRES_INPUT','summary_zh':'需要指定采样字段','conditions_zh':'',
       'evidence':[{'source':node['id'],'path':node['path'],'sha256':node['sha256'],
                    'line_start':node['start'],'line_end':node['end'],
                    'quote':'The sampled quantity is configured in fields.'}]}
    semantic={'facts':[f],'foundation_snapshot':foundation['snapshot']}
    semantic['snapshot']=b.sha(semantic)
    review={'semantic_snapshot':semantic['snapshot'],'decisions':[{'fact':f['id'],'status':'accept'}]}
    return foundation,semantic,review


def test_only_reviewed_facts_are_returned_with_exact_source(engine):
    foundation,semantic,review=semantic_fixture(engine)
    domain=d.build(engine,foundation,semantic,review)
    packet,audit=locate(engine,'sampling fields',6000,domain=domain)
    assert packet['facts'] and audit['selected_facts']
    ev=packet['facts'][0]['evidence'][0]
    assert ev['quote'] in (engine.skill/'corpus'/ev['path']).read_text()
    plain,_=locate(engine,'sampling fields',6000,graph=False,domain=domain)
    assert not plain['facts'] and not plain['relations']
    review['decisions'][0]['status']='reject'
    assert not d.build(engine,foundation,semantic,review)['facts']
    with pytest.raises(ValueError,match='review required'):d.build(engine,foundation,semantic)


def test_tampered_claim_or_source_is_rejected(engine):
    foundation,semantic,review=semantic_fixture(engine)
    bad=copy.deepcopy(semantic);bad['facts'][0]['evidence'][0]['quote']='Invented source sentence'
    with pytest.raises(ValueError,match='digest mismatch'):d.build(engine,foundation,bad,review)
    bad['snapshot']=b.sha({k:v for k,v in bad.items() if k!='snapshot'})
    review['semantic_snapshot']=bad['snapshot']
    with pytest.raises(ValueError,match='quote mismatch'):d.build(engine,foundation,bad,review)
    domain=d.build(engine)
    domain['facts'].append({'fake':True})
    with pytest.raises(ValueError,match='digest mismatch'):locate(engine,'sampling',domain=domain)


def test_explicit_case_and_reverse_relation_keep_logical_type(engine):
    packet,_=locate(engine,'caseA sampling fields',6000)
    assert packet['matched_cases']==['tutorials/caseA']
    assert packet['locations'][0]['path'].startswith('tutorials/caseA/')
    packet,_=locate(engine,'sampled quantity',6000)
    assert any(r['type']=='REFERS_TO_DEFINITION' and r['traversal']=='reverse' for r in packet['relations'])
    with pytest.raises(ValueError,match='case_unavailable'):locate(engine,'sampling',case='doesNotExist')


def test_small_budget_and_long_line_preview(engine):
    packet,_=locate(engine,'sampling fields',1000)
    assert len(b.wire(packet))<=1000
    for item in packet['locations']:
        raw=''.join((engine.skill/'corpus'/item['path']).read_text().splitlines(keepends=True)[item['start']-1:item['end']])
        assert raw.startswith(item['preview']) and item['preview']
        assert item['preview_complete']==(raw==item['preview'])


def test_identifiers_next_to_chinese_and_inside_longer_names():
    assert d.named('caseA','caseA案例的网格')
    assert d.named('ArrheniusRate','使用ArrheniusRate时')
    assert not d.named('caseA','caseAB')
    assert not d.named('caseA','mapped_caseA')


def test_ancestor_conditions_do_not_import_sibling_or_unrelated_claims(engine):
    from locate import fact_candidates
    domain=d.build(engine)
    child=next(uid for uid,m in domain['metadata'].items() if m['name']=='sampling')
    parent=domain['metadata'][child]['ancestors'][0]
    sibling=next(m['section'] for m in domain['metadata'].values() if m['name']=='otherModel')
    def fact(fid,section,subject):
        return {'id':fid,'section':section,'subject':{'name':subject},'object':{'name':'fields'},
                'relation':'LIMITED_TO','summary_zh':'','conditions_zh':''}
    domain['facts']=[fact('ancestor',parent,'sampling model'),fact('sibling',sibling,'sampling model'),
                     fact('unrelated',parent,'viscosity')]
    found=fact_candidates(domain,[child],{'sampling':1},'sampling')
    assert [f['id'] for _,f in found]==['ancestor']
