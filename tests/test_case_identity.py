from pathlib import Path
from types import SimpleNamespace
import hashlib,json
import pytest
from experiments.retrieval_method.case_identity import phase_identity,attach_identity

@pytest.fixture
def data(tmp_path,monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]/'.dsh/skills/blastfoam-knowledge/scripts'))
    path='tutorials/demo/constant/phaseProperties';file=tmp_path/'corpus'/path;file.parent.mkdir(parents=True)
    file.write_text('phases ( fuel ambient );\nfuel { type basic; }\nambient { type basic; }\n')
    engine=SimpleNamespace(skill=tmp_path,graph={'inventory':{path:hashlib.sha256(file.read_bytes()).hexdigest()}})
    return engine,{'case':'tutorials/demo','locations':[]},file

def test_identity_comes_from_declaration_and_changed_source_rejected(data):
    engine,p,file=data
    result=phase_identity(engine,p)
    assert result['phases']==['fuel','ambient']
    assert result['source']['entry']=='phases'
    file.write_text('phases ( water air );')
    with pytest.raises(ValueError,match='changed'):phase_identity(engine,p)

def test_nonliteral_and_duplicate_declarations_not_guessed(data):
    engine,p,file=data
    for raw in ['phases $other;','phases ( air air );','phases ( a b ); phases ( c d );','#include "other"\nphases ( a b );']:
        file.write_text(raw);engine.graph['inventory'][result_path(p)]=hashlib.sha256(file.read_bytes()).hexdigest()
        assert phase_identity(engine,p) is None

def result_path(p):return p['case']+'/constant/phaseProperties'

def test_budget_preserves_bindings_and_edits_without_mutating_input():
    p={'locations':[{'id':'n','text':'x'*900,'complete':True}], 'relations':[{'source':'a','target':'b'}], 'model_draft':{'edits':[{'entry':'x','value':'1'}]}}
    identity={'phases':['fuel','air'],'source':{'path':'constant/phaseProperties','entry':'phases'}}
    r=attach_identity(p,identity,1000)
    assert r['case_identity']==identity and not r['locations'][0]['complete']
    assert r['relations']==p['relations'] and r['model_draft']==p['model_draft']
    assert len(p['locations'][0]['text'])==900
    assert len(json.dumps(r,ensure_ascii=False,separators=(',',':')))<=1000


def test_digest_can_be_read_from_source_when_inline_budget_is_full():
    identity={'phases':['a','b'],'source':{'path':'x','entry':'phases'},'sha256':'f'*64}
    p={'locations':[],'metadata':'x'*850}
    r=attach_identity(p,identity,1000)
    assert r['case_identity']['phases']==['a','b']
    assert r['case_identity']['source']==identity['source']
    assert 'sha256' not in r['case_identity']
