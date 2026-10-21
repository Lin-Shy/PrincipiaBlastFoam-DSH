"""Run the fixed fifteen masked answers after complete control calibration review."""
import argparse
import json
from pathlib import Path
import sys
from chapter2_prepare_local_actual_audit import read, sha
from chapter2_local_compact_score_execution import score_local_answer
from chapter2_qwen_local import LocalQwenClient, DEFAULT_SETTINGS
from chapter2_qwen_compact_grammar import compact_grammar_requests


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)


def review_audit_input(root, cal, row, files, registered):
    audit = json.loads(read(files[-1])['request']['messages'][-1]['content'].removesuffix('\n/no_think'))
    if 'original_material' in audit:
        return audit
    score = read(cal/'sessions'/row['control_id']/'score.json')
    stop = read(root/'audit/local_qwen_transition_001/compact_calibration_timeout_terminal.json')
    if (score.get('status') != 'judge_unknown' or score.get('reason') != 'preserved_local_transport_timeout'
            or score.get('metrics') != dict(complete_valid_answer=None,complete_lower=0,complete_upper=1)
            or len(files) != 1 or read(files[0]).get('status') != 'transport_error'
            or stop.get('failed_request') != files[0].relative_to(cal).as_posix()
            or stop.get('failed_request_sha256') != sha(files[0])
            or row.get('model_judgments_available') is not False):
        raise ValueError('Missing source-stage response is not a bound transport unknown')
    planned = root/row['planned_audit_request']
    oldscore_path = planned.parent.parent/'score.json'
    oldscore = read(oldscore_path)
    if (registered['inputs_sha256'].get(str(planned)) != sha(planned)
            or row.get('planned_audit_request_sha256') != sha(planned)
            or registered['inputs_sha256'].get(str(oldscore_path)) != sha(oldscore_path)
            or oldscore['result_relative_path'] != 'sessions/'+row['control_id']+'/result.json'):
        raise ValueError('Transport-unknown review planned source drift')
    requests = sorted(planned.parent.glob('*.json'))
    if planned != requests[-1] or score['unattempted_stage_indices'] != list(range(1,len(requests))):
        raise ValueError('Interrupted source audit stage accounting drift')
    return json.loads(read(planned)['request']['messages'][-1]['content'])


def validate_controls(root):
    cal = root/'development/local_score_calibration_004'
    report = read(cal/'report.json')
    if report.get('numeric_thresholds_passed') is not True or report.get('overall', {}).get('controls') != 42:
        raise ValueError('Complete numeric calibration has not passed')
    registration_path = cal/'registration.json'
    if report.get('registration_sha256') != sha(registration_path):
        raise ValueError('Calibration report registration drift')
    native_path = root/'audit/local_qwen_transition_001/local_calibration004_native_terminal.json'
    native = read(native_path)
    if (native.get('native_returncode') != 0 or native.get('completed_controls') != 42
            or native.get('report_sha256') != sha(cal/'report.json')):
        raise ValueError('Complete native calibration terminal evidence required')
    for name, value in native['files_sha256'].items():
        if sha(cal/name) != value:
            raise ValueError('Calibration terminal file drift')
    expected = {r['control_id'] for r in report['rows']}
    controls_path = root/'development/score_controls_003/expected-controls.json'
    controls = read(controls_path)
    registered = read(registration_path)
    if registered['inputs_sha256'].get(str(controls_path)) != sha(controls_path):
        raise ValueError('Fixed calibration controls drift')
    if len(report['rows']) != 42 or len(expected) != 42 or expected != {r['control_id'] for r in controls['controls']}:
        raise ValueError('Calibration control identities incomplete')
    for row in report['rows']:
        if row['score_file_sha256'] != sha(cal/'sessions'/row['control_id']/'score.json'):
            raise ValueError('Calibration report score binding drift')
    corpus = Path(read(root/'development/formal_preparation_005/local-resources.json')['corpus'])
    reviewed = set()
    bindings = {str(native_path):sha(native_path), str(cal/'report.json'):sha(cal/'report.json')}
    for path in sorted(cal.glob('semantic-review-batch-*.json')):
        batch = read(path)
        if batch.get('candidate') != 'compact_local_004' or batch.get('human_truth') is not False:
            raise ValueError('Review provenance mismatch')
        for row in batch['rows']:
            cid = row['control_id']
            if cid not in expected or cid in reviewed or row.get('changes_to_automatic_score') is not False:
                raise ValueError('Review identity or score replacement mismatch')
            folder = cal/'sessions'/cid
            if sha(folder/'score.json') != row['score_sha256']:
                raise ValueError('Reviewed score drift')
            for name, value in row['request_sha256'].items():
                if sha(folder/'requests'/name) != value:
                    raise ValueError('Reviewed response drift')
            files = sorted((folder/'requests').glob('*.json'))
            if set(row['request_sha256']) != {p.name for p in files} or not files:
                raise ValueError('Review must bind every stage response')
            audit = review_audit_input(root, cal, row, files, registered)
            spans = list(audit['original_material'].values())
            if row['originals'] != [{k:s[k] for k in ('path','sha256','start','end')} for s in spans]:
                raise ValueError('Review original source identity drift')
            for span in spans:
                source = corpus/span['path']
                lines = source.read_text(encoding='utf-8').splitlines()
                if sha(source) != span['sha256'] or any(lines[r['number']-1] != r['text'] for r in span['lines']):
                    raise ValueError('Reviewed original source drift')
            reviewed.add(cid)
        bindings[str(path)] = sha(path)
    if reviewed != expected:
        raise ValueError('All 42 original-source reviews required before actual-answer audit')
    return bindings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--activity', type=Path, required=True)
    parser.add_argument('--settings', type=Path, default=DEFAULT_SETTINGS)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    root = args.activity.resolve()
    bindings = validate_controls(root)  # Before credentials, client, outputs, or network.
    out = root/'development/local_actual_answer_audit_004'
    prep = read(out/'preparation.json')
    budget = read(out/'input-budget.json')
    for data in (prep, budget):
        for name, value in data['inputs_sha256'].items():
            path = Path(name)
            if not path.is_absolute():
                path = root/path
            if sha(path) != value:
                raise ValueError('Masked input or budget binding drift')
    rows = prep['rows']
    if len(rows) != 15 or budget['answers'] != 15 or budget['planned_requests'] != 55:
        raise ValueError('Fixed fifteen-answer scope required')
    if not args.execute:
        print(json.dumps(dict(ready=True, answers=15, planned_requests=55, model_calls=0)))
        return
    old = root/'development/actual_answer_scoring_001'
    protocol = read(old/'protocol.json')
    for name, value in protocol['source_sha256'].items():
        if sha(old/'runtime'/name) != value:
            raise ValueError('Frozen v7 parser drift')
    sys.path.insert(0, str(old/'runtime/src'))
    sys.path.insert(0, str(old/'runtime/experiments/retrieval_method'))
    import chapter2_partial_answer_scoring as partial
    import chapter2_reasoning_answer_scoring as reasoning
    make_requests = partial.source_free_requests
    inputs = {r['review_id']:r for r in read(root/'development/actual_answer_review_001/evaluation_only/inputs.json')}
    resources = read(root/'development/formal_preparation_005/local-resources.json')
    tokenizer_dir = Path(resources['tokenizer_qwen3-14b'])
    for name, value in read(tokenizer_dir/'artifact-binding.json')['files'].items():
        if sha(tokenizer_dir/name) != value:
            raise ValueError('Tokenizer drift')
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(str(tokenizer_dir), local_files_only=True)
    count = lambda messages:len(tokenizer.apply_chat_template(messages, tokenize=True,
                                add_generation_prompt=True, enable_thinking=False))
    client = LocalQwenClient('qwen3-14b', out/'unused', args.settings, timeout=600)
    deployment = read(root/'development/local_score_calibration_004/registration.json')
    if client.deployment.endpoint != deployment['endpoint'] or client.deployment.model != deployment['model']:
        raise ValueError('Local deployment differs from calibration')
    reasoning.JUDGE_MODEL = client.deployment.model
    for path in (out/'preparation.json', out/'input-budget.json', Path(__file__)):
        bindings[str(path)] = sha(path)
    for name in ('chapter2_prepare_local_actual_audit.py','chapter2_local_compact_score_execution.py',
                 'chapter2_qwen_local.py','chapter2_qwen_compact_grammar.py',
                 'chapter2_qwen_hard_nonthinking.py','chapter2_qwen_structured_output.py'):
        path = Path(__file__).with_name(name)
        bindings[str(path)] = sha(path)
    registration = dict(schema='compact_local_actual_development_execution_v1', formal_result=False,
                        method_labels_masked=True, selection_changed=False, answers=15,
                        input_sha256=bindings, request_timeout_seconds=600, content_retries=0)
    # Exclusive registration: a stopped run requires explicit recovery assessment.
    save(out/'execution-registration.json', registration)
    observed = []
    budgets = {r['review_id']:r for r in budget['rows']}
    for row in rows:
        rid = row['review_id']; source = inputs[rid]
        payload = {k:source[k] for k in ('question','answer','rubric','original_material')}
        result = read(root/row['result_relative_path'])
        if sha(root/row['result_relative_path']) != row['result_sha256']:
            raise ValueError('Fixed answer drift')
        requests = compact_grammar_requests(make_requests(payload)) if result['status']=='answered' else []
        client.folder = out/'sessions'/rid/'requests'
        stage_budget = dict(budgets[rid], local_context_limit=budget['local_context_limit'],
                            response_schema_policy='candidate_segments_compact_grammar_hard_nonthinking_v1')
        def parse(responses, value, actual):
            partial.source_free_requests = lambda _:actual
            partial.parse_source_free_judgments = lambda rs, v:reasoning.parse_reasoning_judgments(rs,v,requests=actual)
            return partial.parse_partial_judgments(responses,value)
        score = score_local_answer(result,payload,requests,client,stage_budget,count,parse)
        score.update(review_id=rid, question_id=row['question_id'], result_sha256=row['result_sha256'],
                     request_bindings={p.name:sha(p) for p in sorted(client.folder.glob('*.json'))})
        save(out/'sessions'/rid/'score.json',score)
        observed.append(dict(review_id=rid,status=score['status'],score_sha256=sha(out/'sessions'/rid/'score.json')))
        print(json.dumps(dict(completed_answers=len(observed),total=15)),flush=True)
        if score.get('transport_circuit_open') or score.get('reason') in {
                'judge_model_mismatch','local_prompt_token_count_mismatch','judge_usage_unknown_or_budget_violation'}:
            raise RuntimeError('Local actual audit stopped; preserve attempt, no retry')
    save(out/'scoring-completion.json',dict(answers=15,rows=observed,formal_activation=False,
         semantic_review_complete=False,requires_native_terminal_verification=True))


if __name__ == '__main__':
    main()
