"""Offline checks: registering a transport must not silently select another."""
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments/retrieval_method'))
import chapter2_sse_scoring as scoring
import chapter2_sse_record_transport as sse
import chapter2_paced_sse_transport as paced


@pytest.mark.parametrize('policy',[None,paced.POLICY])
def test_exact_registered_installer(monkeypatch,policy):
    calls=[];router=SimpleNamespace();digest='a'*64
    monkeypatch.setattr(sse,'install',lambda *args:calls.append(('sse',args)))
    monkeypatch.setattr(paced,'install',lambda *args:calls.append(('paced',args)))
    amendment={} if policy is None else dict(paced_transport_policy=policy)
    scoring.install_transport(router,amendment,digest)
    assert calls==[('sse' if policy is None else 'paced',(router,digest))]


def test_unknown_policy_rejected_before_installation(monkeypatch):
    def forbidden(*args):pytest.fail('Unregistered transport installed')
    monkeypatch.setattr(sse,'install',forbidden)
    monkeypatch.setattr(paced,'install',forbidden)
    with pytest.raises(ValueError,match='Unexpected paced grading transport'):
        scoring.install_transport(SimpleNamespace(),dict(paced_transport_policy='unknown'),'b'*64)
