from types import SimpleNamespace
import copy
from mcp_servers.principia_retrieval.file_navigation import attach_file_navigation,explicit_case_matches


def fixture():
    calls=[]
    graph={'cases':['tutorials/demo/caseA','tutorials/demo/caseB'],'aliases':{'tutorials/demo/aliasA':'tutorials/demo/caseA'}}
    def locate(*args):calls.append(args);return {'status':'ok','locations':[]}
    nav=SimpleNamespace(navigator=lambda:SimpleNamespace(engine=SimpleNamespace(graph=graph)),locate=locate)
    return calls,nav


def test_binding_preserves_inventory_and_rejects_other_or_ambiguous_case():
    calls,nav=fixture();inv={'found':True,'case_path':'demo/caseA','files':[{'file_path':'constant/x','node_id':'id'}]};before=copy.deepcopy(inv)
    for text in ['change demo/caseB','compare demo/caseA and demo/caseB','no case specified','change demo/caseA2']:
        assert attach_file_navigation(inv,text,nav)==inv
    assert calls==[]
    result=attach_file_navigation(inv,'修改 demo/aliasA',nav)
    assert all(result[k]==v for k,v in inv.items()) and inv==before
    assert result['task_navigation']['original_request_sha256']
    assert calls[0][1]=='demo/caseA'


def test_no_context_no_case_and_graph_failure_keep_inventory():
    calls,nav=fixture();missing={'found':False,'files':[]}
    assert attach_file_navigation(missing,'demo/caseA',nav)==missing and not calls
    inv={'found':True,'case_path':'demo/caseA','files':[]}
    assert attach_file_navigation(inv,'',nav)==inv
    def fail(*a):raise ValueError('source changed')
    nav.locate=fail
    p=attach_file_navigation(inv,'demo/caseA',nav)
    assert p['files']==[] and p['task_navigation']['status']=='navigation_unavailable'
