"""Offline calibration analysis including rejected judge outputs as missing, never zero."""
from pathlib import Path
import collections
import json

import judge_calibration as jc
from judge_contract import calculate, joint_metrics, schema
from judge_api_adapter import build, parse
from judge_statistics import ordinal_agreement
from models import encoded, sha, now


def analyze():
    ph, protocol, out, packets = jc.verify()
    jc.require(not jc.read(jc.AUTH)['authorized'], 'Close the judge queue before analysis')
    jc.human.validate_labels(jc.LABELS, 'calibration')
    labels = {r['sample_id']: r['record'] for r in jc.read(jc.LABELS)['labels']}
    mapping = {r['sample_id']: r for r in jc.read(jc.REVIEW/'administration/sample_mapping.json')['samples'] if r['phase'] == 'calibration'}
    rows = []; statuses = {j: collections.Counter() for j in jc.JUDGES}
    usage = {j: dict(input_tokens=0, output_tokens=0, network_attempts=0, unknown_attempts=0, judge_output_failures=0) for j in jc.JUDGES}
    failure_details = []
    for order, s in enumerate(protocol['sample_ids'], 1):
        packet = packets[s]; criteria = [c['criterion_id'] for c in packet['criteria']]
        row = dict(order=order, sample_id=s, question_id=mapping[s]['task']['id'],
                   generation_failed=packet['generation_failed'], conditional=packet['conditional'],
                   human=joint_metrics(labels[s], criteria, packet['conditional'], packet['generation_failed']),
                   records={'human': labels[s]}, judge_statuses={})
        for j in jc.JUDGES:
            target = out/j/s/'result.json'; r = jc.read(target)
            jc.require(r['protocol_sha256'] == ph and r['sample_id'] == s and r['judge_id'] == j, 'Result binding mismatch')
            statuses[j][r['status']] += 1; row['judge_statuses'][j] = r['status']
            if r['status'] == 'complete':
                actual = joint_metrics(r['record'], criteria, packet['conditional'], packet['generation_failed'])
                jc.require(actual == r['metrics'], 'Stored metric drift')
                row[j] = actual; row['records'][j] = r['record']
            else:
                jc.require(not packet['generation_failed'], 'Deterministic failure score missing')
                row[j] = calculate([None]*len(criteria), None, None if packet['conditional'] else 'not_applicable', packet['conditional'])
                row['records'][j] = None
                usage[j]['judge_output_failures'] += r['status'] == 'judge_output_failure'
                failure_details.append(dict(order=order, sample_id=s, question_id=row['question_id'], judge=j, **{k:r[k] for k in ('status','error','transport_status') if k in r}))
            if packet['generation_failed']:
                jc.require(r['origin'] == 'deterministic_generation_failure' and not (target.parent/'requests').exists(), 'Failure sample must not call API')
                continue
            q = jc.read(target.parent/'requests/000.json')
            profile = jc.calibration_profile(j, protocol['judge_output_token_cap'])
            jc.require(jc.public_profile(profile) == protocol['profiles'][j], 'Profile drift')
            body = build(profile, packet, 'joint', jc.prompt_text(), schema())['body']
            jc.require(q['request'] == body and q['request_sha256'] == protocol['request_hashes'][j][s], 'Request drift or label leak')
            if r['status'] == 'complete':
                jc.require(parse(profile, q['raw_response'], packet, 'joint')['record'] == r['record'], 'Parsed score drift')
            elif r['status'] == 'judge_output_failure':
                try: parse(profile, q['raw_response'], packet, 'joint')
                except (ValueError, TypeError, KeyError) as exc:
                    jc.require(str(exc) == r['error'], 'Failure interpretation changed')
                else: raise ValueError('A rejected output became valid without a recorded revision')
            jc.require(q['transport_attempts'] <= protocol['retry_policy']['max_attempts'], 'Retry bound exceeded')
            for attempt in q['attempts']:
                ap = target.parent/'requests'/attempt['record_file']; ar = jc.read(ap)
                jc.require(sha(ap.read_bytes()) == attempt['record_sha256'] and ar['request'] == body, 'Attempt drift')
                usage[j]['network_attempts'] += ar['transport_attempts']
                if ar['status'] == 'response':
                    wire = ap.with_suffix('.response.bin')
                    jc.require(sha(wire.read_bytes()) == ar['response_sha256'], 'Wire drift')
                    jc.require(ar['raw_response']['model'] == profile['model_id'], 'Model identity mismatch')
                    u = ar['raw_response']['usage']; usage[j]['input_tokens'] += u['prompt_tokens']; usage[j]['output_tokens'] += u['completion_tokens']
                elif ar['transport_attempts']: usage[j]['unknown_attempts'] += 1
        row['dual_mean'] = jc.mean_metrics(row[jc.JUDGES[0]], row[jc.JUDGES[1]])
        row['EAS_arith_differences'] = {j: row[j]['EAS_arith']-row['human']['EAS_arith'] if jc.score_known(row[j]['EAS_arith']) and jc.score_known(row['human']['EAS_arith']) else None for j in (*jc.JUDGES, 'dual_mean')}
        rows.append(row)
    files = {path.relative_to(jc.EXPERIMENT).as_posix(): sha(path.read_bytes()) for path in out.rglob('*') if path.is_file()}
    result = dict(schema='judge_calibration_comparison_v2', analyzed_utc=now(), protocol_sha256=ph,
                  analysis_implementation_sha256=sha(Path(__file__).read_bytes()),
                  phase='calibration_only_not_acceptance', records=60, unique_question_ids=50,
                  human_reference='ai_assisted_human_confirmed_single_reviewer', generation_failures=1,
                  statuses={j: dict(v) for j, v in statuses.items()}, usage=usage, failure_details=failure_details,
                  rejected_judge_output_policy='missing_score_with_fixed_denominator_bounds; never generation_failure_zero; no content_retry',
                  comparisons={j: {key: jc.comparison(rows, j, key) for key in ('EAS_arith','EAS_geo','K','F','A','Strict')} for j in (*jc.JUDGES, 'dual_mean')},
                  common_pair_comparisons={j: {key: jc.comparison([row for row in rows if all(jc.score_known(row[k][key]) for k in ('human',*jc.JUDGES))],j,key) for key in ('EAS_arith','EAS_geo','K','F','A','Strict')} for j in (*jc.JUDGES,'dual_mean')},
                  valid_answers_only={j: {key: jc.comparison(rows, j, key, False) for key in ('EAS_arith','EAS_geo')} for j in (*jc.JUDGES, 'dual_mean')},
                  point_agreement={j: ordinal_agreement([(point['score'], {x['criterion_id']:x['score'] for x in row['records'][j]['points']}[point['criterion_id']] if row['records'][j] else None) for row in rows for point in row['records']['human']['points']]) for j in jc.JUDGES},
                  acceptance_started=False, full_generation_started=False, rules_frozen_for_acceptance=False,
                  implementation_snapshot=jc.read(jc.POINTER)['frozen_manifest'], files=files)
    folder = jc.REVIEW/'ai_calibration'/ph[:12]; folder.mkdir(parents=True, exist_ok=True)
    for name, data in [('comparison.json',result),('per_sample.json',dict(protocol_sha256=ph,samples=rows))]:
        path = folder/name
        jc.require(not path.exists(), 'Never overwrite an analyzed calibration trial')
        with path.open('xb') as stream: stream.write(encoded(data))
    return dict(protocol_sha256=ph, report_folder=folder.relative_to(jc.WORK).as_posix(),
                statuses=result['statuses'], summary={j:result['comparisons'][j]['EAS_arith'] for j in (*jc.JUDGES,'dual_mean')}, usage=usage)


if __name__ == '__main__': print(json.dumps(analyze(), ensure_ascii=False))
