import json
from types import SimpleNamespace
import pytest
from test_evidence_bundle import engine
from mcp_servers.principia_retrieval import knowledge_navigation as n
from mcp_servers.principia_retrieval import server


def test_source_is_bounded_and_cannot_escape_index(engine,monkeypatch):
    monkeypatch.setattr(n,'navigator',lambda:SimpleNamespace(engine=engine))
    path='tutorials/caseA/system/controlDict'
    result=n.source(path,1,100,budget=1000)
    assert len(json.dumps(result,ensure_ascii=False,separators=(',',':')))<=1000
    assert (engine.skill/'corpus'/path).read_bytes().decode('utf-8').startswith(result['text'])
    with pytest.raises(ValueError):n.source('../../outside',1,2)
    with pytest.raises(ValueError):n.source(path,0,3)


def test_actual_case_boundary_is_checked_before_assessment(tmp_path,monkeypatch):
    monkeypatch.setenv('PRINCIPIA_CASE_ROOT',str(tmp_path/'allowed'))
    monkeypatch.setattr(n,'assess',lambda *a: {'unexpected':True})
    with pytest.raises(ValueError,match='must stay within'):server.check_case_dependencies(str(tmp_path/'other'),'blastFoam/freeField')


def test_optional_protocol_trace_preserves_result_and_validation_error(tmp_path,monkeypatch):
    import asyncio
    from mcp.types import TextContent
    sentinel=[TextContent(type='text',text='source evidence')]
    async def call(name,args):
        if name=='bad':raise ValueError('invalid')
        return sentinel
    monkeypatch.setattr(server,'_untraced_call_tool',call)
    monkeypatch.setenv('PRINCIPIA_TOOL_TRACE_DIR',str(tmp_path))
    assert asyncio.run(server.mcp.call_tool('source',{'start':2})) is sentinel
    with pytest.raises(ValueError):asyncio.run(server.mcp.call_tool('bad',{}))
    records=[json.loads(p.read_text()) for p in tmp_path.glob('*.json')]
    assert {x['status'] for x in records}=={'ok','error'}
    assert next(x for x in records if x['status']=='ok')['result'][0]['text']=='source evidence'


def test_dictionary_edit_boundary_is_checked_before_mutation(tmp_path,monkeypatch):
    monkeypatch.setenv('PRINCIPIA_CASE_ROOT',str(tmp_path/'allowed'))
    with pytest.raises(ValueError,match='must stay within'):
        server.edit_case_dictionaries(str(tmp_path/'other'),[server.DictionaryEdit(path='system/controlDict',entry='endTime',value='1')])
