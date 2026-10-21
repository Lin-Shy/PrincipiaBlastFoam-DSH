import hashlib
import json
from pathlib import Path
import pytest
from principia_core.retrieval.knowledge_qa import (
    FrozenKnowledgeCorpus, KnowledgeToolSession, KnowledgeBudget, MANIFEST_SCHEMA,
)

class Backend:
    def __init__(self, rows):self.rows=rows
    def search(self, query, limit):return self.rows[:limit]

def corpus(tmp_path, text='first original line\nsecond original line\nthird original line\n'):
    root=tmp_path/'raw';source=root/'manual/markdown/topic.md';source.parent.mkdir(parents=True);source.write_text(text,encoding='utf-8')
    manifest=tmp_path/'manifest.json'
    manifest.write_text(json.dumps({'schema':MANIFEST_SCHEMA,'files':[{'path':'manual/markdown/topic.md',
        'sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'bytes':len(source.read_bytes()),'lines':len(text.splitlines())}]}),encoding='utf-8')
    return FrozenKnowledgeCorpus(root,manifest),source,manifest

def test_backend_text_cannot_enter_original_source_packet(tmp_path):
    c,_,_=corpus(tmp_path)
    backend=Backend([{'path':'manual/markdown/topic.md','start':1,'end':2,'text':'GOLD_SECRET','labels':{'test':True}}])
    s=KnowledgeToolSession('graph',c,backend)
    reply=s.execute('search',{'query':'topic'})
    assert 'GOLD_SECRET' not in reply and 'labels' not in reply
    assert s.validate_references([{'path':'manual/markdown/topic.md','start':1,'end':2}])
    assert not s.validate_references([{'path':'manual/markdown/topic.md','start':1,'end':3}])

def test_score_side_manifest_rejected(tmp_path):
    _,_,p=corpus(tmp_path)
    v=json.loads(p.read_text());v['schema']='raw_corpus_manifest_v1';v['purpose']='scoring_support_sources_not_the_formal_graph_construction_corpus';p.write_text(json.dumps(v))
    with pytest.raises(ValueError,match='scoring-support'):
        FrozenKnowledgeCorpus(tmp_path/'raw',p)

def test_no_knowledge_arm_cannot_instantiate_source_or_tool(tmp_path):
    c,_,_=corpus(tmp_path)
    with pytest.raises(ValueError,match='must not instantiate'):
        KnowledgeToolSession('none',c,Backend([]))
    s=KnowledgeToolSession('none')
    with pytest.raises(ValueError,match='disabled'):
        s.execute('read_source',{'path':'manual/markdown/topic.md','start':1,'end':1})
    assert not s.delivered_lines

def test_invalid_path_and_boolean_range_consume_calls(tmp_path):
    c,_,_=corpus(tmp_path);s=KnowledgeToolSession('bm25',c,Backend([]),KnowledgeBudget(tool_calls=2))
    assert 'error' in s.execute('read_source',{'path':'../../scoring/annotations.json','start':1,'end':1})
    assert 'error' in s.execute('read_source',{'path':'manual/markdown/topic.md','start':True,'end':1})
    assert len(s.events)==2 and not s.available and not s.delivered_lines

def test_changed_raw_file_never_delivered(tmp_path):
    c,p,_=corpus(tmp_path);p.write_text('changed source\n')
    s=KnowledgeToolSession('e5',c,Backend([]))
    assert 'error' in s.execute('read_source',{'path':'manual/markdown/topic.md','start':1,'end':1})
    assert not s.delivered_lines

def test_budget_clipping_keeps_json_and_only_whole_original_lines(tmp_path):
    c,_,_=corpus(tmp_path,'a'*100+'\n'+'b'*100+'\n'+'c'*100+'\n')
    s=KnowledgeToolSession('hybrid',c,Backend([]),KnowledgeBudget(tool_characters=400,total_characters=400))
    reply=s.execute('read_source',{'path':'manual/markdown/topic.md','start':1,'end':3})
    packet=json.loads(reply)
    assert len(reply)<=400 and s.characters==len(reply)
    assert packet['truncated'] and packet['evidence'][0]['end']<3
    unit=packet['evidence'][0]
    assert unit['next_line']==unit['end']+1
    assert all(len(row['text'])==100 for row in unit['lines'])
    assert not s.validate_references([{'path':unit['path'],'start':1,'end':3}])

def test_repeated_delivery_counts_against_actual_context_budget(tmp_path):
    c,_,_=corpus(tmp_path);s=KnowledgeToolSession('bm25',c,Backend([]))
    args={'path':'manual/markdown/topic.md','start':1,'end':1}
    first=s.execute('read_source',args);second=s.execute('read_source',args)
    assert s.characters==len(first)+len(second)
    assert len(s.delivered_lines)==1
