import copy,hashlib,json
import pytest
from mcp_servers.principia_retrieval.request_context import locate_with_context


def test_original_not_rewritten_query_supplies_constraints():
    calls=[]
    def locate(*args):calls.append(args);return {'status':'ok','locations':[]}
    p=locate_with_context(locate,'gamma=1.4 As=9','demo','const -> sutherland',5000,'gamma=1.5 As=1e-6')
    assert calls==[('gamma=1.5 As=1e-6','demo','',5000)]
    assert p['original_request_sha256']==hashlib.sha256(b'gamma=1.5 As=1e-6').hexdigest()
    locate_with_context(locate,'query','demo','translation',5000)
    assert calls[-1]==('query','demo','translation',5000)


def test_budget_and_no_mutation():
    original={'status':'ok','locations':[{'path':'file','text':'x'*5000,'complete':True}], 'model_draft':{'edits':[{'entry':'gas/transport/As','value':'1e-6'}]}}
    saved=copy.deepcopy(original)
    p=locate_with_context(lambda *a:original,'q','demo','',1000,'request')
    assert len(json.dumps(p,ensure_ascii=False,separators=(',',':')))<=1000
    assert p['model_draft']==original['model_draft'] and not p['locations'][0]['complete']
    assert original==saved
    with pytest.raises(ValueError):locate_with_context(lambda *a:original,'q','demo','',1000,'x'*32769)
