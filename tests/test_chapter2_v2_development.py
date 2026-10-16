from copy import deepcopy
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments/retrieval_method'))
from chapter2_v2_retrieval_probe import covered
from chapter2_v2_metric_diagnosis import macro
from chapter2_v2_development_runner import DeploymentResponse,token_counter,prepared_messages
from chapter2_qwen_local import LocalModel
from chapter2_v2_development_report import physical_requests
from chapter2_v2_retrieval_probe import save


def test_union_of_adjacent_original_spans_covers_gold_but_gap_and_wrong_file_do_not():
    gold=dict(path='manual/a.md',line_start=10,line_end=20)
    assert covered([dict(path='manual/a.md',start=10,end=14),dict(path='manual/a.md',start=15,end=20)],gold)
    assert not covered([dict(path='manual/a.md',start=10,end=14),dict(path='manual/a.md',start=16,end=20)],gold)
    assert not covered([dict(path='manual/b.md',start=1,end=100)],gold)


def test_group_macro_keeps_known_zero_and_unknown_upper_and_does_not_pool_repeats():
    rows=[dict(question_id='A',group='small',value=[0,0])]*3
    rows += [dict(question_id=q,group='large',value=[1,1]) for q in ('B','C')]
    rows += [dict(question_id='D',group='large',value=[0,1])]
    value=macro(rows,lambda r:r['value'])
    assert value['bounds']==[1/3, .5] and value['questions']==4 and value['groups']==2


def test_local_interface_alias_preserves_actual_model_and_provider_receipt():
    actual=dict(model='Qwen3-14B',choices=[dict(message=dict(content='{}'))])
    receipt=dict(status='response',raw_response=actual,model='Qwen3-14B')
    class Client:
        deployment=LocalModel('http://localhost/v1/chat/completions','Qwen3-14B','test')
        def __call__(self,body,turn):return receipt
    result=DeploymentResponse(Client(),'qwen3-14b')({},0)
    assert result['response']['model']=='qwen3-14b'
    assert result['raw_response']['model']=='Qwen3-14B'
    assert result['model']=='Qwen3-14B' and 'response' not in receipt


def test_local_token_counter_counts_actual_no_think_without_mutating_history():
    messages=[dict(role='user',content='question'),dict(role='assistant',content='reply'),dict(role='user',content='source')]
    original=deepcopy(messages);seen=[]
    def count(value):seen.append(value);return len(value[-1]['content'])
    token_counter(count,'small')(messages)
    assert seen[-1][-1]['content']=='source\n/no_think' and messages==original
    token_counter(count,'bulk')(messages)
    assert seen[-1]==original


def test_common_answer_checklist_is_counted_in_exactly_the_messages_submitted():
    original=[dict(role='system',content='common rules'),dict(role='user',content='natural question')]
    counted=[];submitted=[]
    class Client:
        def __call__(self,body,turn):submitted.append(body);return dict(status='transport_error')
    token_counter(lambda messages:counted.append(messages),'bulk','check every subquestion')(original)
    DeploymentResponse(Client(),'qwen3-8b','check every subquestion')(dict(messages=original),0)
    assert counted[0]==submitted[0]['messages']
    assert original[0]['content']=='common rules'


def test_physical_accounting_counts_failures_and_model_overlap_without_copying_result_receipts(tmp_path):
    rows=[dict(started_utc='2026-10-16T01:00:00+00:00',seconds=2,model='qwen3-8b',status='response',raw_response={'usage':{'total_tokens':10}}),
        dict(started_utc='2026-10-16T01:00:01+00:00',seconds=2,model='qwen3-8b',status='transport_error')]
    for i,row in enumerate(rows):save(tmp_path/'development/proxy_matched_001/sessions/method'/str(i)/'requests/00.json',row)
    save(tmp_path/'development/proxy_matched_001/sessions/method/0/result.json',dict(turns=rows))
    result=physical_requests(tmp_path)
    assert result['physical_requests_by_stage']=={'proxy_matched_001':2}
    assert result['known_total_tokens_by_stage']=={'proxy_matched_001':10}
    assert result['missing_usage_by_stage']=={'proxy_matched_001':1}
    assert result['timestamp_overlap_estimate_peak']=={'proxy_matched_001/qwen3-8b':2}


def test_offline_transport_events_count_attempts_and_missing_usage_but_reuse_references_are_free(tmp_path):
    save(tmp_path/'diagnosis/evaluation_only/review/sessions/Q/responses/necessity.json',
        dict(events=[dict(status='transport_error'),dict(status='response',usage={'total_tokens':7})]))
    save(tmp_path/'development/revised/sessions/Q/reuse-references/00.json',
        dict(reused=True,new_physical_requests=0))
    result=physical_requests(tmp_path)
    assert result['physical_requests_by_stage']=={'offline/review':2}
    assert result['known_total_tokens_by_stage']=={'offline/review':7}
    assert result['missing_usage_by_stage']=={'offline/review':1}
