from types import SimpleNamespace
from mcp_servers.principia_retrieval.task_navigation import prepare_task_navigation
import pytest

def test_preflight_uses_unique_explicit_case_and_original_text():
 calls=[]
 def locate(*args):calls.append(args);return {'status':'located','locations':[]}
 nav=SimpleNamespace(navigator=lambda:SimpleNamespace(engine=SimpleNamespace(graph={'cases':['tutorials/blastFoam/demo','tutorials/blastFoam/other'],'aliases':{}})),locate=locate)
 request='修改 blastFoam/demo 中的参数'
 result=prepare_task_navigation(request,nav)
 assert calls==[(request,'blastFoam/demo','',5000)]
 assert result['original_request_sha256']
 assert prepare_task_navigation('修改参数',nav)['status']=='not_applicable'
 assert prepare_task_navigation('比较 blastFoam/demo 和 blastFoam/other',nav)['status']=='not_applicable'
 assert len(calls)==1
 with pytest.raises(ValueError):prepare_task_navigation(' ',nav)
