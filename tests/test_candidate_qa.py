import json
import sys
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments/retrieval_method'))
import candidate_qa as c


def test_prompt_requires_literal_case_and_configuration_identifiers():
    instruction = c.prompt(c.DEFAULTS)
    assert "必须原样保留这些字面标识符" in instruction
    assert "高置信的常用化学式、字段名或配置名" in instruction
    assert "提示本身不是答案证据" in instruction
    assert "模型选择器或启用条件" in instruction
    assert "include/引用到参数文件的链" in instruction


def test_navigation_prompt_requires_explicit_original_source_read():
    instruction = c.prompt({**c.DEFAULTS, "navigation_only": True})
    assert 'action:"read_sources"' in instruction
    assert "选择1到6个候选" in instruction
    assert "覆盖needs中的每个缺口" in instruction
    assert "保留两侧候选" in instruction
    assert "节点value选择" in instruction
    assert "不得直接引用任何导航元数据" in instruction


def test_navigation_prompt_explains_bounded_original_context():
    instruction = c.prompt({
        **c.DEFAULTS, "navigation_only": True, "source_context_lines": 16,
    })
    assert "前后最多16行" in instruction
    assert "收窄到真正支持主张的精确行" in instruction


def test_read_sources_type_form_is_normalized_as_a_valid_action():
    action = c.qa.normalize_action({
        "type": "read_sources",
        "candidate_ids": ["candidate-1"],
    })
    assert action["action"] == "read_sources"
    assert action["candidate_ids"] == ["candidate-1"]


def test_formula_to_tutorial_values_gets_deterministic_relation_slots():
    question = "在 reacting 教程中氧气黏度随温度怎么算，实际取值在哪个文件？"
    needs = ["公式", "实际取值"]
    completed = c.relation_complete_needs(question, needs)
    assert needs == ["公式", "实际取值"]
    assert any("模型名" in value for value in completed)
    assert any("include" in value for value in completed)
    assert c.relation_complete_needs(question, completed) == completed


def test_relation_slots_are_not_added_to_unrelated_or_full_requests():
    assert c.relation_complete_needs("教程里的网格在哪里？", ["路径"]) == ["路径"]
    full = [str(index) for index in range(8)]
    assert c.relation_complete_needs(
        "教程中模型公式怎么算，实际值在哪个文件？", full
    ) == full


def test_draft_and_verifier_require_atomic_fully_supported_claims():
    assert "不得硬合并为一个复合主张" in c.DRAFT
    assert "跨文件比较必须拆成" in c.DRAFT
    assert "模型选择器、启用条件和include指令属于必要证据链" in c.DRAFT
    assert "不能只写公式和末端数值" in c.PLAN
    assert "引用只支持其中一部分，必须判为false" in c.VERIFY
    assert "每个列举项都必须在该主张自己的精确引用原文中出现" in c.VERIFY


def test_claim_evidence_packet_isolates_exact_citations_per_claim():
    draft={"claims":[
        {"text":"a和b都存在","references":[{"path":"a","start":1,"end":1}]},
        {"text":"b存在","references":[{"path":"b","start":2,"end":2}]},
    ]}
    packet=c.claim_evidence_packet(draft,{"a":{"1":"object a"},"b":{"2":"object b"}})
    assert packet["schema_valid"]
    assert packet["claims"][0]["references"][0]["quote"]=="1: object a"
    assert "object b" not in json.dumps(packet["claims"][0],ensure_ascii=False)
    assert packet["claims"][1]["references"][0]["quote"]=="2: object b"


def test_claim_evidence_packet_marks_unseen_and_overbroad_ranges_invalid(monkeypatch):
    monkeypatch.setattr(c,"MAX_VERIFICATION_QUOTE_CHARS",3)
    draft={"claims":[{"text":"x","references":[
        {"path":"a","start":1,"end":1},{"path":"missing","start":1,"end":1},
    ]}]}
    refs=c.claim_evidence_packet(draft,{"a":{"1":"long"}})["claims"][0]["references"]
    assert refs[0]["invalid_reason"]=="citation_range_too_broad_for_semantic_verification"
    assert refs[1]["invalid_reason"]=="citation_not_in_already_seen_lines"


def test_twelve_claim_provider_overrun_is_released_when_fully_verified():
    claims = [
        {"text": f"claim-{index}", "references": [{"path": "a", "start": 1, "end": 1}]}
        for index in range(12)
    ]
    votes = {"claims": [
        {"index": index, "supported": True, "reason": "literal"}
        for index in range(12)
    ]}
    answer, complete = c.release_verified(
        {"claims": claims, "unknowns": []}, votes, {"a": {"1": "claim"}}
    )
    assert complete
    assert len(answer["answer"].splitlines()) == 12


def test_verification_cannot_release_new_or_unseen_claims():
    seen={'a':{'1':'model A','2':'active false'}}
    draft={'claims':[{'text':'model A','references':[{'path':'a','start':1,'end':1}]},
                     {'text':'is active','references':[{'path':'a','start':2,'end':2}]},
                     {'text':'hidden claim','references':[{'path':'a','start':3,'end':3}]}],'unknowns':[]}
    votes={'claims':[{'index':0,'supported':True},{'index':1,'supported':False,'reason':'source says false'},
                     {'index':2,'supported':True}]}
    answer,complete=c.release_verified(draft,votes,seen)
    assert complete
    assert answer['answer']=='model A'
    assert len(answer['references'])==1
    assert len(answer['unknowns'])==2


def test_incomplete_verifier_rejects_the_submission():
    answer,complete=c.release_verified({'claims':[{'text':'x','references':[]}]},{'claims':[]},{})
    assert not complete and not answer['answer']


def test_huge_or_boolean_citation_end_is_rejected_without_iteration():
    for end in [10**20,True]:
        value=c.check_plan({'claims':[{'references':[{'path':'a','start':1,'end':end}]}]},{'a':{'1':'x'}})
        assert not value['all_ranges_valid']


def test_complete_agent_budget_and_all_visible_evidence_replay(tmp_path,monkeypatch):
    seen={'a':{'1':'alpha'}}
    responses=[];bodies=[]
    action={'action':'finish','reason':'fixture'}
    plan={'claims':[],'unknowns':[]}
    draft={'claims':[{'text':'alpha','references':[{'path':'a','start':1,'end':1}]}],'unknowns':[]}
    verdict={'claims':[{'index':0,'supported':True,'reason':'literal'}]}
    for value in [action,plan,draft,verdict]:
        responses.append({'raw_response':{'model':c.qa.MODEL,'choices':[{'finish_reason':'stop','message':{'content':json.dumps(value)}}]}})
    def fetch(folder,name,body,key):bodies.append((name,body));return responses.pop(0)
    class FakeSession:
        def __init__(self,*args):self.seen=seen;self.needs=[]
    monkeypatch.setattr(c.base,'fetch',fetch);monkeypatch.setattr(c,'Session',FakeSession)
    engine=SimpleNamespace(run=tmp_path,options=c.DEFAULTS,graph_path=None)
    q={'id':'fixture-p1','item_id':'fixture','question':'alpha?'}
    result=c.run_one(engine,q,'retrieval_first','fixture')
    assert result['parsed_answer']['answer']=='alpha'
    assert [name for name,_ in bodies]==['step-01','plan','final','claim-check']
    assert [body['max_tokens'] for _,body in bodies]==[700,700,2400,700]
    assert result['returned_characters']<=800
    assert 'qualified_claim' not in result['parsed_answer']


def test_malformed_verification_indices_and_unknowns_fail_closed():
    from candidate_qa import release_verified
    draft={'claims':[{'text':'claim','references':[{'path':'a','start':1,'end':1}]}],'unknowns':[]}
    for index in (False,[],{},'0'):
        parsed,valid=release_verified(draft,{'claims':[{'index':index,'supported':True}]},{'a':{'1':'claim'}})
        assert not valid and not parsed['answer']
    draft['unknowns']=None
    assert not release_verified(draft,{'claims':[{'index':0,'supported':True}]},{'a':{'1':'claim'}})[1]


def test_navigation_candidates_are_batch_read_from_original_corpus(tmp_path):
    corpus=tmp_path/'corpus';corpus.mkdir()
    source=corpus/'source.txt';source.write_text('alpha\nbeta\ngamma\n')
    engine=SimpleNamespace(
        options={**c.DEFAULTS,'navigation_only':True,'source_context_lines':0},
        corpus=corpus,
        files={'source.txt':['alpha','beta','gamma']},
        manifest={'source.txt':{'sha256':c.qa.digest(source.read_bytes())}},
        graph_path=tmp_path/'graph.json',
    )
    session=c.Session(engine,'retrieval_first','question')
    locate={'status':'ok','candidates':[{
        'id':'candidate-1',
        'sources':[{'path':'source.txt','start':2,'end':3}],
    }]}
    session.restore({'action':'locate','needs':[]},locate)
    assert session.seen == {}

    result,accounting=session.dispatch(
        {'action':'read_sources','candidate_ids':['candidate-1']},2000
    )

    assert result['status']=='ok'
    assert result['selected_candidate_ids']==['candidate-1']
    assert result['items'][0]['text']=='2: beta\n3: gamma'
    assert session.seen=={'source.txt':{'2':'beta','3':'gamma'}}
    assert accounting['content']['source_ranges_requested']==1


def test_selected_sources_get_fair_bounded_context_and_merge_overlaps(tmp_path):
    corpus=tmp_path/'corpus';corpus.mkdir()
    lines=[f'line-{index}' for index in range(1,11)]
    source=corpus/'source.txt';source.write_text('\n'.join(lines)+'\n')
    engine=SimpleNamespace(
        options={**c.DEFAULTS,'navigation_only':True,'source_context_lines':2},
        corpus=corpus,files={'source.txt':lines},
        manifest={'source.txt':{'sha256':c.qa.digest(source.read_bytes())}},
        graph_path=tmp_path/'graph.json',
    )
    session=c.Session(engine,'retrieval_first','question')
    session.restore({'action':'locate','needs':[]},{'status':'ok','candidates':[
        {'id':'candidate-1','sources':[{'path':'source.txt','start':4,'end':4}]},
        {'id':'candidate-2','sources':[{'path':'source.txt','start':6,'end':6}]},
    ]})

    result,accounting=session.dispatch(
        {'action':'read_sources','candidate_ids':['candidate-1','candidate-2']},4000
    )

    assert result['context_lines_requested']==2
    assert result['context_lines_applied']==2
    assert [(item['start'],item['end']) for item in result['items']]==[(2,8)]
    assert set(session.seen['source.txt'])=={str(index) for index in range(2,9)}
    assert accounting['content']['source_ranges_requested']==2
    assert accounting['content']['source_ranges_returned']==1


def test_source_context_shrinks_to_fit_response_cap(tmp_path):
    corpus=tmp_path/'corpus';corpus.mkdir()
    lines=['x'*80 for _ in range(20)]
    source=corpus/'source.txt';source.write_text('\n'.join(lines)+'\n')
    engine=SimpleNamespace(
        options={**c.DEFAULTS,'navigation_only':True,'source_context_lines':8},
        corpus=corpus,files={'source.txt':lines},
        manifest={'source.txt':{'sha256':c.qa.digest(source.read_bytes())}},
        graph_path=tmp_path/'graph.json',
    )
    session=c.Session(engine,'retrieval_first','question')
    session.restore({'action':'locate','needs':[]},{'status':'ok','candidates':[
        {'id':'candidate-1','sources':[{'path':'source.txt','start':10,'end':10}]},
    ]})
    zero_item=session.contextual_source_items([('source.txt',10,10)],0)
    zero={'status':'ok','items':zero_item,'next_offset':None,
          'selected_candidate_ids':['candidate-1'],'context_lines_requested':8,
          'context_lines_applied':0}
    cap=len(c.qa.wire(zero))

    result,_=session.dispatch(
        {'action':'read_sources','candidate_ids':['candidate-1']},cap
    )

    assert result['status']=='ok'
    assert result['context_lines_applied']==0
    assert [(item['start'],item['end']) for item in result['items']]==[(10,10)]
    assert len(c.qa.wire(result))<=cap
