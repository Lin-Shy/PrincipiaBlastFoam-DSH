import hashlib
from pathlib import Path
from types import SimpleNamespace
import pytest
from experiments.retrieval_method.attribute_target import resolve_target

@pytest.fixture
def env(tmp_path,monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1]/'.dsh/skills/blastfoam-knowledge/scripts'))
    path='tutorials/demo/constant/phaseProperties';file=tmp_path/'corpus'/path;file.parent.mkdir(parents=True)
    e=SimpleNamespace(skill=tmp_path,graph={'inventory':{},'aliases':{}})
    def write(a='1.5',b='1.4'):
        file.write_text('phases ( first second );\nfirst { equationOfState { gamma '+a+'; } }\nsecond { equationOfState { gamma '+b+'; } }')
        e.graph['inventory'][path]=hashlib.sha256(file.read_bytes()).hexdigest()
    write();return e,write,file


def test_unique_source_object_and_equivalent_numeric_spelling(env):
    e,write,file=env
    for q in ['比热比为1.5的气体','比热比(gamma)为1.50','heat capacity ratio of 1.5','gamma=1.5 gamma is 1.50']:
        r=resolve_target(e,'demo',q);assert r['status']=='unique' and r['phase']=='first'
        assert r['observed'][0]['entry']=='first/equationOfState/gamma'
    assert resolve_target(e,'demo','gamma=1.4')['phase']=='second'


def test_zero_multiple_unsupported_and_conflicting_matches(env):
    e,write,file=env
    assert resolve_target(e,'demo','gamma=1.6')['status']=='no_match'
    write(b='1.5');assert resolve_target(e,'demo','gamma=1.5')['status']=='ambiguous'
    for q in ['gamma>1.4','比热比不是1.5','gamma=1.4 gamma=1.5']:
        assert resolve_target(e,'demo',q)['status']=='unsupported_or_conflicting_predicate'
    assert resolve_target(e,'demo','As=1.5e-6 Ts=120') is None


def test_unresolved_other_phase_prevents_unique_claim_and_source_hash_matters(env):
    e,write,file=env;write(b='$unknown')
    assert resolve_target(e,'demo','gamma=1.5')['status']=='unresolved_source'
    file.write_text('phases ( fake other );')
    with pytest.raises(ValueError,match='changed'):resolve_target(e,'demo','gamma=1.5')


def test_locator_enforces_target_and_budget(env,monkeypatch):
    import json
    from experiments.retrieval_method import native_draft_server as api
    e,write,file=env
    search=SimpleNamespace(engine=e,search=object())
    monkeypatch.setattr(api.knowledge_navigation,'navigator',lambda:search)
    calls=[]
    def locate(q,case,**kw):
        calls.append((q,kw));return {'status':'ok','case':'tutorials/demo','locations':[]}
    search.locate=locate
    monkeypatch.setattr(api,'explicit_inputs',lambda *a:{})
    monkeypatch.setattr(api,'draft_model_edits',lambda *a:{'status':'draft_requires_review','edits':[{'entry':'second/transport/As'}]})
    p=api.locate_drafts('gamma=1.5 sutherland As=1e-6 Ts=120','demo')
    assert p['status']=='target_not_located' and not p.get('model_draft')
    assert p['target_resolution']['phase']=='first'
    assert 'gamma' not in calls[0][0] and 'first' in calls[0][0]
    assert calls[0][1]['budget']==12000  # Resolve evidence before final packing.
    assert len(json.dumps(p,ensure_ascii=False,separators=(',',':')))<=5000
    for query in ['gamma=1.6','gamma>1.4']:
        calls.clear();p=api.locate_drafts(query,'demo',budget=1000)
        assert p['status']=='target_unresolved' and not calls
        assert len(json.dumps(p,ensure_ascii=False,separators=(',',':')))<=1000


@pytest.mark.parametrize('tail',[
 '目标气体其余的比热比、热力学和状态方程设置也保持原样。',
 '比热比保持不变。',
 'Keep gamma and other thermodynamic settings unchanged.',
 'Leave heat capacity ratio unchanged.',
])
def test_preservation_mentions_do_not_reject_selector(env,tail):
    e,_,_=env
    assert resolve_target(e,'demo','比热比为1.5的气体改用sutherland；'+tail)['phase']=='first'
    assert resolve_target(e,'demo',tail) is None


@pytest.mark.parametrize('tail',[
 'gamma=1.4保持不变', 'gamma>1.4保持不变','keep gamma higher than 1.4 unchanged',
 '比热比较大的保持原样','gamma不是1.5保持不变','keep gamma equal to 1.4 unchanged',
])
def test_preservation_does_not_hide_conflicting_or_unsupported_selectors(env,tail):
    e,_,_=env
    assert resolve_target(e,'demo','gamma=1.5;'+tail)['status']=='unsupported_or_conflicting_predicate'


def test_english_translation_predicates_are_not_silently_ignored(env):
    e,_,_=env
    for text in ['specific heat ratio 1.5','gamma 1.5','heat capacity ratio is 1.5']:
        assert resolve_target(e,'demo','比热比为1.5; '+text)['phase']=='first'
    assert resolve_target(e,'demo','比热比为1.5; specific heat ratio 1.4')['status']=='unsupported_or_conflicting_predicate'
    assert resolve_target(e,'demo','gamma=1.5; keep specific heat ratio unchanged')['phase']=='first'
