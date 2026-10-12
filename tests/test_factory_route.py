import hashlib,json
from pathlib import Path
from types import SimpleNamespace
import pytest
from experiments.retrieval_method.factory_route import FactoryRoute
from experiments.retrieval_method.lookup_semantics import digest

@pytest.fixture
def setup(tmp_path,monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]/'.dsh/skills/blastfoam-knowledge/scripts'))
    (tmp_path/'source.C').write_text('call();\n')
    ev={'path':'source.C','start':1,'end':1,'quote':'call();'}
    g={'scope':'test','entry':'start','end':'end','inventory':{'source.C':hashlib.sha256(b'call();\n').hexdigest()},'nodes':[{'id':n,'claim':n,'review':'accept','evidence':[ev]} for n in ['start','end']],'edges':[{'source':'start','target':'end','review':'accept','relation':'REVIEWED_DEFAULT_ROUTE'}]}
    def save():
        g['snapshot']=digest({k:v for k,v in g.items() if k!='snapshot'});(tmp_path/'graph.json').write_text(json.dumps(g));return FactoryRoute(tmp_path/'graph.json')
    engine=SimpleNamespace(skill=tmp_path,graph={'inventory':{}})
    def source(rel,text):
        p=tmp_path/'corpus/tutorials/demo'/rel;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text);engine.graph['inventory']['tutorials/demo/'+rel]=hashlib.sha256(text.encode()).hexdigest()
    source('system/controlDict','application blastFoam;');source('constant/phaseProperties','phases ( a b );')
    packet={'case':'tutorials/demo','locations':[{'dictionary':'b/thermoType','path':'tutorials/demo/constant/phaseProperties'}]}
    return g,save,engine,source,packet

def test_binding_requires_default_context_and_route(setup):
    g,save,e,source,p=setup;r=save();identity={'phases':['a','b']}
    assert r.reference(e,p,identity)
    assert r.reference(e,p,{'phases':['a']}) is None
    source('constant/phaseProperties','phases ( a b ); systemType custom;');assert r.reference(e,p,identity) is None
    source('constant/phaseProperties','phases ( a b );');source('system/controlDict','application blastFoam; libs ( custom );');assert r.reference(e,p,identity) is None
    source('system/controlDict','application otherSolver;');assert r.reference(e,p,identity) is None
    source('system/controlDict','application blastFoam;');g['edges']=[];assert save().reference(e,p,identity) is None

def test_factory_sources_fail_closed(setup):
    g,save,e,source,p=setup;r=save()
    with pytest.raises(ValueError):r.read('../source.C')
    (r.root/'source.C').write_text('changed')
    with pytest.raises(ValueError,match='changed'):save()


def test_inline_fact_requires_reachable_reviewed_endpoint(setup):
    g,save,e,source,p=setup
    assert save().inline_evidence() is None

    g['end']='compile_fallback';g['nodes'][-1]['id']='compile_fallback'
    g['nodes'][-1]['claim']='Compilation can fail.'
    g['edges'][0]['target']='compile_fallback'
    fact=save().inline_evidence()
    assert fact['claim']=='Compilation can fail.'
    assert fact['sources']==[{'path':'factory_route/source.C','start':1,'end':1}]
    assert 'unvalidated' in fact['scope']
    g['edges']=[]
    assert save().inline_evidence() is None


def test_transport_projection_requires_basic_phases_and_connected_evidence(setup):
    g,save,e,source,p=setup
    identity={'phases':['a','b']}
    assert not save().reference(e,p,identity)['basic_phase_flow']
    source('constant/phaseProperties','phases ( a b ); a { type basic; } b { type basic; }')
    assert save().reference(e,p,identity)['basic_phase_flow']
    source('constant/phaseProperties','phases ( a b ); a { type basic; } b { type reacting; }')
    assert not save().reference(e,p,identity)['basic_phase_flow']
    g['end']='compile_fallback';g['nodes'][-1]['id']='compile_fallback';g['edges'][0]['target']='compile_fallback'
    g['nodes'].append(dict(id='transport_flow_summary',claim='reviewed binding',review='accept',evidence=g['nodes'][0]['evidence']))
    assert 'transport_flow' not in save().inline_evidence(include_transport=True)
    g['edges'].append(dict(source='start',target='transport_flow_summary',relation='REVIEWED_FLOW',review='accept'))
    assert 'transport_flow' not in save().inline_evidence()
    flow=save().inline_evidence(include_transport=True)['transport_flow']
    assert flow['claim']=='reviewed binding'
    assert flow['source_snapshot']==g['snapshot']
    assert flow['runtime_status'].startswith('unverified:')
    page=json.loads(save().node_source('transport_flow_summary'))
    assert page['node']['evidence']==g['nodes'][-1]['evidence']
    assert page['snapshot']==g['snapshot']
    with pytest.raises(ValueError,match='unknown factory node'):
        save().node_source('../source.C')


def test_shortest_directed_path_preserves_relation_family_and_handles_cycles(setup):
    g,save,e,source,p=setup
    ev=g['nodes'][0]['evidence']
    g['nodes'].append(dict(id='middle',claim='constructor binding',review='accept',evidence=ev))
    g['edges']=[dict(source=a,target=b,relation=r,review='accept') for a,b,r in
                [('start','middle','CALL'),('middle','end','CALL'),('middle','start','CALL'),('start','end','SUMMARY')]]
    route=save()
    assert len(route.evidence_path('start','end'))==1
    assert [x['target'] for x in route.evidence_path('start','end',['CALL'])]==['middle','end']
    assert route.evidence_path('end','start') is None
    assert route.evidence_path('start','start')==[]
    with pytest.raises(ValueError,match='unknown factory endpoint'):route.evidence_path('missing','end')
    with pytest.raises(ValueError,match='disconnected'):route.path_source('end','start')
    g['inline_path']={'relations':['CALL'],'scope':'source only'}
    page=save().path_source('start','end')
    assert 'constructor binding' in page and '--SUMMARY-->' not in page
    assert 'factory_route/source.C:1-1' in page


def test_inline_path_retains_intermediate_bindings(setup):
    g,save,e,source,p=setup
    g['end']='compile_fallback';g['nodes'][-1]['id']='compile_fallback';g['edges'][0]['target']='compile_fallback'
    g['nodes'][0]['label']='solver entry';g['nodes'][1]['label']='conditional compile'
    g['inline_path']={'relations':['REVIEWED_DEFAULT_ROUTE'],'scope':'build/load unverified'}
    result=save().inline_evidence()
    assert result['construction_path']=='solver entry → conditional compile'
    assert result['source']=='factory_route/path/start/compile_fallback'
    assert result['source_snapshot']==g['snapshot']
