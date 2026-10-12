import hashlib
import json
from pathlib import Path
import pytest
from experiments.retrieval_method.lookup_semantics import LookupSemantics,digest
from experiments.retrieval_method import native_lookup_server as api

@pytest.fixture
def fixture(tmp_path):
    raw='caller();\nlookup();\n';(tmp_path/'source.C').write_text(raw)
    ev={'path':'source.C','start':1,'end':2,'quote':'lookup();'}
    graph={'scope':'test version only','inventory':{'source.C':hashlib.sha256(raw.encode()).hexdigest()},'nodes':[{'id':i,'review':'accept','evidence':[ev],'claim':i} for i in ['entry','rule']], 'edges':[{'source':'entry','target':'rule','relation':'CALLS','evidence':ev,'review':'accept'}], 'binding':{'condition_snapshot':'bound','condition':'viscous','path':'system/fvSolution','parent':'solvers','leaf':'solver','entry_node':'entry','rule_node':'rule'}}
    def save():
        graph['snapshot']=digest({k:v for k,v in graph.items() if k!='snapshot'})
        (tmp_path/'graph.json').write_text(json.dumps(graph))
        return tmp_path/'graph.json'
    path=save()
    packet={'status':'conditional_edit_drafts','condition_snapshot':'bound','conditional_drafts':[{'id':'viscous','edits_if_true':[{'path':'system/fvSolution','entry':'solvers/U/solver','value':'PBiCGStab'}]}]}
    return path,graph,packet,save

def test_relation_requires_traversable_reviewed_chain(fixture):
    path,g,p,save=fixture
    assert LookupSemantics(path).reference(p)['targets']=={'system/fvSolution':['solvers/U']}
    g['edges']=[];save()
    assert LookupSemantics(path).reference(p) is None

def test_source_identity_and_review(fixture):
    path,g,p,save=fixture
    (path.parent/'source.C').write_text('tampered')
    with pytest.raises(ValueError,match='source changed'):LookupSemantics(path)
    g['nodes'][0]['review']='pending';save()
    with pytest.raises(ValueError,match='unreviewed'):LookupSemantics(path)

def test_context_and_literal_targets(fixture):
    path,g,p,save=fixture;engine=LookupSemantics(path)
    p['condition_snapshot']='different'
    assert engine.reference(p) is None
    p['condition_snapshot']='bound';edit=p['conditional_drafts'][0]['edits_if_true'][0]
    for key in ['solvers/(U|e)/solver','other/U/solver','solvers/U/tolerance']:
        edit['entry']=key;assert engine.reference(p) is None
    edit['entry']='solvers/U/solver';edit['value']=None
    assert engine.reference(p) is None

def test_evidence_range_and_confinement(fixture):
    path,g,p,save=fixture
    g['nodes'][0]['evidence'][0]['end']=999;save()
    with pytest.raises(ValueError,match='range'):LookupSemantics(path)
    g['nodes'][0]['evidence'][0]['end']=2
    g['inventory']['../outside']=g['inventory']['source.C']
    g['nodes'][0]['evidence'][0]['path']='../outside';save()
    with pytest.raises(ValueError,match='escapes'):LookupSemantics(path)

def test_source_api_and_budget(fixture,monkeypatch):
    path,g,p,save=fixture
    monkeypatch.setenv('PRINCIPIA_LOOKUP_GRAPH',str(path))
    monkeypatch.setattr(api,'locate_drafts',lambda *a:p)
    assert 'lookup_semantics' in api.locate('query','case')
    p['padding']='x'*4900
    assert api.locate('query','case',budget=5000) is p
    result=api.source('lookup_semantics/rule',1,80,1000)
    assert len(json.dumps(result,ensure_ascii=False,separators=(',',':')))<=1000
    assert 'lookup_semantics/source.C' in result['text']
    assert api.source('lookup_semantics/source.C')['text']=='caller();\nlookup();\n'
    with pytest.raises(ValueError):api.source('lookup_semantics/../outside')
    with pytest.raises(ValueError):api.source('lookup_semantics/rule',20,10)
