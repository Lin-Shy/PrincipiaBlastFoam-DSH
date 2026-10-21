"""在全部既有开发控制上单独验证本地裁判，不混入正式评分。"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
from datetime import datetime, timezone
from chapter2_qwen_local import LocalQwenClient, prepare_body
from chapter2_qwen_structured_output import constrain_requests


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as out:
        json.dump(value, out, ensure_ascii=False, indent=2)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--activity', type=Path, required=True)
    p.add_argument('--dataset', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--recovery-receipt', type=Path, required=True)
    args = p.parse_args()
    old = args.activity.resolve() / 'development/score_calibration_011'
    controls = args.activity.resolve() / 'development/score_controls_003'
    protocol = read(old / 'protocol.json')
    if sha(args.dataset / 'dataset-seal.json') != protocol['dataset_seal_sha256']:
        raise ValueError('Calibration dataset seal differs')
    seal = read(args.dataset / 'dataset-seal.json')
    # Dataset seal format is checked explicitly before annotations are used.
    for name, expected in seal['files'].items():
        if sha(args.dataset / name) != expected:
            raise ValueError('Calibration dataset artifact drift')
    for name, expected in protocol['source_sha256'].items():
        if sha(old / 'runtime' / name) != expected:
            raise ValueError('Frozen v7 source drift')
    sys.path.insert(0, str(old / 'runtime/src'))
    sys.path.insert(0, str(old / 'runtime/experiments/retrieval_method'))
    import chapter2_reasoning_answer_scoring as reasoning
    import chapter2_partial_answer_scoring as partial
    from chapter2_partial_answer_scoring import source_free_requests, parse_partial_judgments
    from chapter2_report_score_calibration import summarize
    annotations = {a['id']: a for a in read(args.dataset / 'scoring/annotations.json')}
    expected = read(controls / 'expected-controls.json')
    dev = set(read(args.dataset / 'split.json')['ids']['dev'])
    if not {c['question_id'] for c in expected['controls']} <= dev:
        raise ValueError('Local calibration must use development controls only')
    old_scores = {read(f)['result_relative_path']: f for f in old.glob('sessions/*/score.json')}
    recovery = read(args.recovery_receipt)
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(recovery['started_utc'])).total_seconds()
    if (recovery.get('provider') != 'qwen_local' or recovery.get('status') != 'response'
            or recovery.get('raw_response', {}).get('model') != 'Qwen3-14B' or not 0 <= age <= 900):
        raise ValueError('Fresh exact local structured availability response required')
    stop_path = args.activity.resolve() / 'audit/local_qwen_transition_001/structured_calibration_timeout_terminal.json'
    stop = read(stop_path)
    if stop['native_returncode'] != 1 or stop['request_reissue_allowed'] is not False:
        raise ValueError('Original timeout terminal proof required')
    for name, value in stop['preserved_files_sha256'].items():
        if sha(args.output / name) != value: raise ValueError('Stopped calibration artifact drift')
    client = LocalQwenClient('qwen3-14b', args.output / 'requests', timeout=600)
    if client.deployment.endpoint != recovery['endpoint']: raise ValueError('Recovery endpoint mismatch')
    registered_runner = Path(__file__).with_name('chapter2_calibrate_qwen_local_structured.py').resolve()
    inputs = {str(Path(__file__).with_name('chapter2_qwen_structured_output.py').resolve()): sha(Path(__file__).with_name('chapter2_qwen_structured_output.py')),
              str(old / 'protocol.json'): sha(old / 'protocol.json'),
              str(controls / 'expected-controls.json'): sha(controls / 'expected-controls.json'),
              str(registered_runner): sha(registered_runner),
              str(Path(__file__).with_name('chapter2_qwen_local.py').resolve()):
                  sha(Path(__file__).with_name('chapter2_qwen_local.py'))}
    cases = []
    for control in expected['controls']:
        cid = control['control_id']
        rel = f'sessions/{cid}/result.json'
        result_path = controls / 'generation' / rel
        if sha(result_path) != protocol['result_bindings'][rel]:
            raise ValueError('Control answer binding mismatch')
        result = read(result_path)
        oldscore = old_scores[rel]
        request_files = sorted((oldscore.parent / 'requests').glob('*.json'))
        originals = [read(f)['request'] for f in request_files]
        audit = json.loads(originals[-1]['messages'][-1]['content'])
        ann = annotations[control['question_id']]
        payload = dict(question=audit['question'], answer=result['answer'],
                       original_material=audit['original_material'], rubric=dict(
                       required_points=ann['required_points'],
                       condition_discrimination=ann['labels']['condition_discrimination'],
                       applicability=ann['applicability']))
        requests = source_free_requests(payload)
        if [r['body'] for r in requests] != originals:
            raise ValueError('Reconstructed control request differs from frozen original')
        requests = constrain_requests(requests)
        for f in [result_path, oldscore, *request_files]:
            inputs[str(f)] = sha(f)
        cases.append((cid, payload, requests))
    registration = dict(schema='local_qwen_v7_structured_calibration_v1', formal_result=False,
        model=client.deployment.model, endpoint=client.deployment.endpoint,
        control_count=len(cases), request_count=sum(len(r) for _, _, r in cases),
        inputs_sha256=inputs, acceptance_criteria=expected['acceptance_before_scoring'],
        changes=['local endpoint and configured model identity', 'documented /no_think suffix',
                 'registered JSON schema constrains fields and actual segment IDs; semantic verdict options retained'],
        content_retries=0, raw_response_rewriting=False, quality_based_selection=False)
    target = args.output / 'registration.json'
    if not target.exists(): raise ValueError('Recovery requires the existing structured calibration')
    amendment = dict(schema='local_structured_timeout_continuation_v1',original_registration_sha256=sha(target),
        stop_receipt_sha256=sha(stop_path),availability_response_sha256=sha(args.recovery_receipt),
        execution_sha256=sha(Path(__file__)),new_request_timeout_seconds=600,
        known_failed_request=stop['failed_request'],failed_request_reissued=False,
        failed_control_policy='retain unknown; do not execute later stages of the interrupted control',
        remaining_control_policy='same registered request bodies; one attempt each, no quality retry')
    amendment_path = args.output / 'transport-continuation-001.json'
    if amendment_path.exists():
        if read(amendment_path) != amendment: raise ValueError('Recovery amendment drift')
    else: save(amendment_path, amendment)
    if target.exists():
        prior = read(target)
        runner_key = str(registered_runner)
        comparison = json.loads(json.dumps(registration))
        comparison['inputs_sha256'][runner_key] = prior['inputs_sha256'][runner_key]
        if prior != comparison:
            raise ValueError('Local calibration registration drift')
        if prior['inputs_sha256'][runner_key] != registration['inputs_sha256'][runner_key]:
            initial = args.activity.resolve() / 'audit/local_qwen_transition_001/calibration_runner_initial.py'
            if sha(initial) != prior['inputs_sha256'][runner_key]:
                raise ValueError('Original runner not preserved')
            amendment = dict(original_registration_sha256=sha(target),
                original_runner_sha256=sha(initial), corrected_runner_sha256=sha(Path(__file__)),
                change='Bind frozen parser callbacks to actual local requests; no semantic rule or response edits',
                completed_requests_reissued=False)
            amend_path = args.output / 'parser_bridge_amendment.json'
            if amend_path.exists():
                if read(amend_path) != amendment: raise ValueError('Parser bridge amendment drift')
            else: save(amend_path, amendment)
    else:
        save(target, registration)
    # Configure the expected local identity in the frozen parser only. Raw
    # requests/responses are never rewritten to claim the historical identity.
    reasoning.JUDGE_MODEL = client.deployment.model
    observations = []
    for cid, payload, requests in cases:
        folder = args.output / 'sessions' / cid
        client.folder = folder / 'requests'
        actual_requests = [dict(r, body=prepare_body(r['body'], client.deployment)) for r in requests]
        responses = []
        for i, request in enumerate(requests):
            f = client.folder / f'{i:02d}.json'
            if f.exists():
                record = read(f)
                if (record['request'] != actual_requests[i]['body']
                        or record['endpoint'] != client.deployment.endpoint
                        or record['status'] == 'in_flight'):
                    raise ValueError('Existing local attempt unresolved or drifted; no reissue')
            else:
                record = client(request['body'], i)
            responses.append(dict(record, response=record.get('raw_response')))
            if record['status'] in {'transport_error', 'http_rejected'}:
                if str(f.relative_to(args.output)).replace('\\','/') != stop['failed_request'].replace('\\','/'):
                    raise RuntimeError('New transport failure; preserve attempt and stop')
                if sha(f) != stop['failed_request_sha256']: raise ValueError('Known failure changed')
                break
        def strict(rs, value):
            return reasoning.parse_reasoning_judgments(rs, value, requests=actual_requests)
        # The old v7 function has no injection parameters. Bind its two module
        # callbacks to the same actual requests and unchanged strict parser.
        partial.source_free_requests = lambda value: actual_requests
        partial.parse_source_free_judgments = strict
        if responses[-1]['status'] in {'transport_error','http_rejected'}:
            score = dict(status='judge_unknown',reason='preserved_local_transport_timeout',
                metrics=dict(complete_valid_answer=None,complete_lower=0,complete_upper=1),
                unattempted_stage_indices=list(range(len(responses),len(requests))))
        else:
            score = parse_partial_judgments(responses, payload)
        score['deployment'] = 'qwen_local'
        score.update(control_id=cid, registration_sha256=sha(target),
                     request_bindings={str(i): sha(client.folder / f'{i:02d}.json') for i in range(len(responses))})
        scorepath = folder / 'score.json'
        if scorepath.exists():
            if read(scorepath) != score:
                raise ValueError('Local score parsing drift')
        else:
            save(scorepath, score)
        observations.append(dict(control_id=cid, candidate_matches_expected=True,
            status=score['status'], complete=score.get('metrics', {}).get('complete_valid_answer'),
            reason=score.get('reason'), score_file_sha256=sha(scorepath)))
        print(json.dumps(dict(completed_controls=len(observations), total=len(cases))), flush=True)
    report = summarize(expected, observations)
    report.update(registration_sha256=sha(target), local_deployment=True,
                  historical_formal_results_modified=False)
    save(args.output / 'report.json', report)
    print(json.dumps(dict(overall=report['overall'], by_class=report['by_class'],
        numeric_thresholds_passed=report['numeric_thresholds_passed'])), flush=True)


if __name__ == '__main__':
    main()
