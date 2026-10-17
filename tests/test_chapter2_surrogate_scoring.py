from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'experiments/retrieval_method'))
from chapter2_surrogate_scoring import contains_surrogate, wrap


def test_malformed_candidate_is_unknown_without_any_model_or_tokenizer_call():
    def forbidden(*args):raise AssertionError('Malformed input must not be submitted or repaired')
    value = wrap(forbidden)({'status': 'answered'}, {'answer': '原始\udb06Q'}, forbidden, forbidden)
    assert value['status'] == 'judge_unknown' and value['counted_input_tokens'] == 0
    assert value['metrics'] == dict(complete_valid_answer=None, complete_lower=0, complete_upper=1)
    assert value['content_repair'] is False


def test_valid_unicode_and_literal_escape_delegate_exact_objects():
    result={'status':'answered'};payload={'answer':'中文😀 ' + r'\udb06Q'};client=object();counter=object();calls=[]
    def original(*args):calls.append(args);return {'unchanged':True}
    assert wrap(original)(result,payload,client,counter) == {'unchanged':True}
    assert calls == [(result,payload,client,counter)]


def test_generation_failure_stays_in_original_zero_score_path():
    def original(*args):return {'status':'generation_failed','metrics':{'complete_valid_answer':0}}
    assert wrap(original)({'status':'invalid_action'},None,None,None)['metrics']['complete_valid_answer'] == 0


def test_nested_values_detect_surrogates_without_confusing_valid_emoji():
    assert contains_surrogate({'nested':[{'text':'\udfff'}]})
    assert not contains_surrogate({'nested':['😀','中文',123,None]})
