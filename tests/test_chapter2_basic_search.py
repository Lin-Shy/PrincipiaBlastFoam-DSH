"""Baseline isolation, raw evidence fidelity, pagination and consumer parity."""
import ast
import hashlib
import inspect
import json
from pathlib import Path
import sys
import textwrap
import pytest

PROJECT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(PROJECT/'experiments/retrieval_method'),str(PROJECT/'src')]
from chapter2_basic_search_tools import BasicSearchSession,basic_specs,path_matches
from chapter2_basic_search_agent import BasicSearchAgent
from principia_core.retrieval.knowledge_qa import FrozenKnowledgeCorpus,KnowledgeBudget,MANIFEST_SCHEMA
from principia_core.retrieval.knowledge_agent import AutonomousKnowledgeAgent,SYSTEM
from chapter2_basic_search_200 import CHECKLIST
from chapter2_qa_deployment import ANSWER_CHECKLIST


@pytest.fixture
def corpus(tmp_path):
    files={'manual/a.md':'model JWL\npressure alpha\nother\n','tutorials/z/constant/p':'model JWL\npressure beta\n',
        'tutorials/z/system/controlDict':'application blastFoam;\n'}
    rows=[]
    for name,text in files.items():
        p=tmp_path/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(text.encode())
        rows.append(dict(path=name,sha256=hashlib.sha256(p.read_bytes()).hexdigest(),bytes=p.stat().st_size,lines=len(text.splitlines())))
    manifest=tmp_path/'manifest.json';manifest.write_text(json.dumps(dict(schema=MANIFEST_SCHEMA,files=rows)),encoding='utf-8')
    return FrozenKnowledgeCorpus(tmp_path,manifest)


def test_glob_is_path_only_and_has_no_relevance_order(corpus):
    tools=BasicSearchSession(corpus)
    packet=json.loads(tools.execute('glob',{'pattern':'**/p'}))
    assert packet['paths']==['tutorials/z/constant/p'] and not tools.delivered_lines
    assert path_matches('manual/a.md','manual/**/*.md')
    assert not path_matches('tutorials/z/constant/p','tutorials/*/p')
    assert {t['name'] for t in basic_specs()}=={'glob','grep','read_source'}
    assert tools.backend is None


def test_grep_regex_source_ledger_and_reading(corpus):
    tools=BasicSearchSession(corpus)
    packet=json.loads(tools.execute('grep',{'pattern':'(?i)jwl|beta','include':'**/*'}))
    evidence=packet['evidence']
    assert [(r['path'],r['start']) for r in evidence]==[('manual/a.md',1),('tutorials/z/constant/p',1),('tutorials/z/constant/p',2)]
    assert evidence[0]['lines']==[dict(number=1,text='model JWL')]
    assert tools.validate_references([dict(path='manual/a.md',start=1,end=1)])
    assert not tools.validate_references([dict(path='manual/a.md',start=1,end=2)])
    tools.execute('read_source',dict(path='manual/a.md',start=1,end=3))
    assert tools.validate_references([dict(path='manual/a.md',start=1,end=3)])
    assert json.loads(tools.execute('grep',{'pattern':'中文模型别名'}))['evidence']==[]


def test_pagination_and_budget_do_not_claim_undelivered_lines(corpus):
    tools=BasicSearchSession(corpus,KnowledgeBudget(tool_calls=3,tool_characters=400,total_characters=900))
    packet=json.loads(tools.execute('grep',{'pattern':'JWL|pressure'}))
    assert packet['truncated'] and packet['next_offset']>0
    first=set(tools.delivered_lines)
    next_packet=json.loads(tools.execute('grep',{'pattern':'JWL|pressure','offset':packet['next_offset']}))
    assert next_packet['evidence'] and first < tools.delivered_lines
    tools.execute('read_source',dict(path='manual/../../scoring/annotations.json',start=1,end=1))
    assert tools.events[-1]['status']=='tool_error' and tools.characters<=900
    assert not tools.available


def test_unsupported_specialized_tools_are_rejected(corpus):
    tools=BasicSearchSession(corpus)
    for name in ['search','graph','bm25','e5','catalog']:
        tools.execute(name,{'query':'JWL'})
        assert tools.events[-1]['status']=='tool_error'
    assert not tools.delivered_lines


def test_agent_action_loop_is_unchanged_except_declared_tool_specs():
    old=inspect.getsource(AutonomousKnowledgeAgent.run).replace('specs=tool_specs(self.tools.method)','specs=basic_specs()')
    new=inspect.getsource(BasicSearchAgent.run)
    assert ast.dump(ast.parse(textwrap.dedent(old)))==ast.dump(ast.parse(textwrap.dedent(new)))
    import chapter2_basic_search_agent as basic
    assert basic.SYSTEM==SYSTEM
    assert CHECKLIST.replace('"name":"grep","arguments":{"pattern":"具体英文标识"}',
        '"name":"search","arguments":{"query":"具体标识与所需含义"}')==ANSWER_CHECKLIST
