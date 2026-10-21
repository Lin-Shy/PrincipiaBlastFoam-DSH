"""本地统一裁判的单回答执行规则；不修改冻结评分，不隐式重试。"""
import hashlib
import json
from chapter2_qwen_local import prepare_body
from chapter2_qwen_structured_output import constrain_requests


def request_sha(body):
    data=json.dumps(body,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf-8')
    return hashlib.sha256(data).hexdigest()


def unknown(reason, **details):
    return dict(status='judge_unknown', reason=reason,
                metrics=dict(complete_valid_answer=None,complete_lower=0,complete_upper=1),**details)


def score_local_answer(result, payload, requests, client, budget, count_tokens, parse):
    """Consume pre-audited actual requests and a parser expecting local identity.

    `parse` must use the unchanged v7 rules with the supplied actual requests;
    both actual and old logical model identifiers stay out of raw rewriting.
    The driver must validate activation and original-review gates before this
    function or client construction. No files or credentials are loaded here.
    """
    if result['status']!='answered':
        if requests or budget['actual_request_sha256'] or budget['actual_input_tokens']:
            raise ValueError('Generation failure must not have judge requests')
        return dict(status='generation_failed',reason=result['status'],counted_input_tokens=0,
                    metrics=dict(complete_valid_answer=0,complete_lower=0,complete_upper=0))
    if not requests:raise ValueError('Answered result needs fixed judge stages')
    actual=[dict(r,body=prepare_body(r['body'],client.deployment)) for r in requests]
    hashes=[request_sha(r['body']) for r in actual]
    counts=[count_tokens(r['body']['messages']) for r in actual]
    if any(type(n) is not int or n<1 for n in counts):raise ValueError('Invalid actual input token count')
    if hashes!=budget['actual_request_sha256'] or counts!=budget['actual_input_tokens']:
        raise ValueError('Actual request differs from sealed budget audit')
    expected=constrain_requests(requests)
    if any(r['body'].get('max_tokens')!=4096 or r['body'].get('temperature')!=0
           or r['body'].get('response_format')!=e['body']['response_format'] for r,e in zip(actual,expected)):
        raise ValueError('Frozen judge decoding settings drift')
    if budget.get('response_schema_policy')!='candidate_segments_json_schema_v1':
        raise ValueError('Structured request budget policy not registered')
    metadata=dict(planned_counted_input_tokens=sum(counts),stage_input_tokens=counts,
                  planned_stage_request_sha256=hashes,counted_input_tokens=0,
                  deployment='qwen_local',content_retries=0)
    if any(n>32768 for n in counts):
        return unknown('judge_input_budget_exhausted',**metadata)
    if any(n+4096>budget['local_context_limit'] for n in counts):
        return unknown('local_deployment_context_exceeded',**metadata)
    responses=[]
    for index, request in enumerate(requests):
        record=client(request['body'],index)
        metadata['counted_input_tokens']+=counts[index]
        if record.get('request')!=actual[index]['body'] or record.get('request_sha256')!=hashes[index]:
            raise ValueError('Recorded local request binding drift')
        if record.get('endpoint')!=client.deployment.endpoint:
            raise ValueError('Recorded local endpoint drift')
        if record['status'] in {'transport_error','http_rejected'}:
            return unknown(record['status'],transport_circuit_open=True,**metadata)
        raw=record.get('raw_response')
        if record['status']=='response':
            if not isinstance(raw,dict) or raw.get('model')!=client.deployment.model:
                return unknown('judge_model_mismatch',**metadata)
            usage=raw.get('usage') or {}
            prompt=usage.get('prompt_tokens')
            completion=usage.get('completion_tokens')
            if type(prompt) is not int or prompt!=counts[index]:
                return unknown('local_prompt_token_count_mismatch',**metadata)
            if type(completion) is not int or not 0<=completion<=4096:
                return unknown('judge_usage_unknown_or_budget_violation',**metadata)
        responses.append(dict(record,response=raw))
    score=parse(responses,payload,actual)
    if score.get('status')=='judge_unknown':
        return {**score,**unknown(score.get('reason','unclassified_parse_failure'),**metadata)}
    if score.get('status') not in {'judged','partially_judged'}:
        raise ValueError('Unexpected v7 parser status')
    value=score.get('metrics',{}).get('complete_valid_answer')
    if value is not None and (type(value) is not int or value not in (0,1)):
        raise ValueError('Invalid completeness value')
    return {**score,**metadata}


def validate_local_activation(activation, calibration, semantic_review, budget_report):
    """Pure pre-network gate. File hashes are checked separately by the driver."""
    if activation.get('schema')!='uniform_local_judge_activation_v1':
        raise ValueError('Local judge execution has no registered activation')
    if activation.get('scope')!='full_fixed_13536_answers':
        raise ValueError('Selective rescoring is not the registered local comparison')
    if activation.get('response_schema_policy')!='candidate_segments_json_schema_v1':
        raise ValueError('Structured decoding policy is not registered')
    if calibration.get('numeric_thresholds_passed') is not True:
        raise ValueError('Complete local calibration has not passed')
    if calibration.get('overall',{}).get('controls')!=42:
        raise ValueError('All 42 calibration controls required')
    if (semantic_review.get('schema')!='local_judge_development_semantic_acceptance_v1'
        or semantic_review.get('accepted') is not True
        or semantic_review.get('reviewed_control_count')!=42
        or semantic_review.get('pending_controls')!=[]
        or semantic_review.get('human_truth') is not False):
        raise ValueError('Complete explicit AI source review is required')
    if (budget_report.get('sessions')!=13536 or len(budget_report.get('rows',[]))!=13536
        or budget_report.get('fixed_output_cap')!=4096
        or budget_report.get('answers_truncated') is not False):
        raise ValueError('Complete actual request budget audit required')
    if activation.get('context_overflow_policy')!='retain_unknown_without_truncation':
        raise ValueError('Unregistered local capacity policy')
    return True
