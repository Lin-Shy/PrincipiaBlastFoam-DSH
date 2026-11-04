"""Bound, calibration-only AI judging. Never unlocks acceptance or generation."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import argparse
import collections
import json
import math
import statistics

import human_review as human
from judge_api_adapter import build, central_profile, parse, canonical, digest
from judge_contract import VERSION, schema, joint_metrics
from judge_statistics import cluster_intervals, dual_eas, ordinal_agreement
from models import WORK, EXPERIMENT, Deployment, encoded, sha, now, settings
from transport_retry import RetryingClient, RetryPolicy, atomic, request_lock, storage_path

HERE = Path(__file__).resolve().parent
REVIEW = human.ROOT
POINTER = EXPERIMENT/'release/planning/judge_calibration.json'
AUTH = EXPERIMENT/'release/planning/judge_calibration_authorization.json'
JUDGES = ('gpt_sol', 'deepseek_flash')
LABELS = REVIEW/'calibration/calibration_completed_human_labels.json'
INPUT_FIELDS = ('sample_id', 'question', 'answer', 'generation_failed', 'conditional',
                'criteria', 'sources', 'applicability', 'acceptable_answer_range', 'critical_errors')
SOURCE_FILES = ('judge_calibration.py', 'judge_api_adapter.py', 'judge_contract.py',
                'judge_statistics.py', 'human_review.py', 'models.py', 'transport_retry.py',
                'judge_prompt.txt', 'scoring_rules.json', 'matrix.py', 'test_judge_calibration.py')


def read(path):
    return json.loads(storage_path(path).read_text(encoding='utf-8'))


def require(condition, message):
    if not condition:
        raise ValueError(message)


def packet_for(p):
    """Explicit allowlist: no reviewer labels, identities, methods or other judges."""
    return dict(schema_version=VERSION, **{key: p[key] for key in INPUT_FIELDS})


def prompt_text():
    return ((HERE/'judge_prompt.txt').read_text(encoding='utf-8') +
            '\n统一评分规则（各档位含义均适用）：\n' +
            (HERE/'scoring_rules.json').read_text(encoding='utf-8'))


def public_profile(p):
    return dict({k: v for k, v in p.items() if k != 'base_url'},
                endpoint_sha256=sha((p['base_url'].rstrip('/')+'/chat/completions').encode()),
                profile_sha256=digest(p))


def calibration_profile(judge, output_cap):
    require(type(output_cap) is int and output_cap in (2048, 8192), 'Unregistered judge output cap')
    p = central_profile(judge)
    p.update(output_token_cap=output_cap, input_token_cap=32768-output_cap)
    return p


def protected_inputs():
    paths = [REVIEW/'calibration/packets.json', LABELS,
             REVIEW/'calibration/human_review_completion.json',
             REVIEW/'administration/sample_mapping.json',
             REVIEW/'acceptance/packets.json', REVIEW/'acceptance/blank_labels.json',
             human.DATASET/'binding.json', human.DATASET/'open/model/questions.json',
             human.DATASET/'open/scoring/annotations.json', human.DATASET/'open/scoring/evidence.json',
             human.DATASET/'objective/model/questions.json', human.DATASET/'objective/scoring/annotations.json',
             WORK/'PrincipiaBlastFoam-DSH/config/llm/models.yaml',
             WORK/'PrincipiaBlastFoam-DSH/config/llm/providers.yaml']
    return {p.relative_to(WORK).as_posix(): sha(p.read_bytes()) for p in paths}


def check_other_gates():
    gate = read(EXPERIMENT/'release/planning/execution.json')
    for key in ('formal_generation_authorized', 'formal_full_matrix_authorized',
                'acceptance_generation_authorized', 'judge_calls_authorized', 'transport_recovery_authorized'):
        require(gate[key] is False, 'Unrelated dispatch must remain closed: '+key)
    require(gate['allowed_stages'] == [], 'Unrelated stages enabled')
    pack = read(REVIEW/'acceptance/packets.json')
    require(not pack['enabled_for_review'] and all(p['answer'] is None for p in pack['samples']),
            'Acceptance must remain locked and ungenerated')
    require(not (REVIEW/'administration/acceptance_lock.json').exists(), 'Acceptance was unlocked')


def prepare(infrastructure_recovery=False, revise_judge_cap=False, output_cap=2048):
    previous = None
    if POINTER.exists():
        require(infrastructure_recovery or revise_judge_cap, 'Preserve the existing calibration trial; do not reset it')
        require(not (infrastructure_recovery and revise_judge_cap), 'Choose one revision reason')
        old = read(POINTER); oldroot = EXPERIMENT/old['output_root']
        require(not read(AUTH)['authorized'], 'Previous judge dispatch is still open')
        results = list(oldroot.glob('*/*/result.json'))
        if infrastructure_recovery:
            require(len(results) == 2 and all(read(path)['status'] == 'technical_unresolved' for path in results),
                    'Infrastructure recovery is only for the two failed initial connections, without scores')
            require(not list(oldroot.rglob('*.response.bin')), 'Received responses require an explicit new calibration design')
            reason = 'Sandbox connections failed; no HTTP responses received. Retry in network-enabled execution, preserving the first trial.'
        else:
            require(old['status'] == 'calibration_dispatch_closed', 'Drain the prior calibration dispatch before revision')
            require(output_cap == 8192, 'This technical revision only raises the judge-only output cap to 8192')
            truncated = []
            for path in results:
                if read(path)['status'] == 'judge_output_failure':
                    raw = read(path.parent/'requests/000.json')['raw_response']
                    require(raw['choices'][0]['finish_reason'] == 'length', 'Not an output-cap failure')
                    truncated.append(path)
            require(truncated, 'A judge truncation must be evidenced before this revision')
            reason = 'Judge reasoning consumed the inherited 2048 cap and truncated scoring JSON. Uniformly rejudge all 60 under judge-only 8192; preserve every old result; no score selection or mixing; original answer cap remains 2048.'
        previous = dict(protocol_sha256=old['protocol_sha256'], reason=reason,
                        files={path.relative_to(EXPERIMENT).as_posix(): sha(path.read_bytes()) for path in oldroot.rglob('*') if path.is_file()})
        (oldroot/'closed_dispatch_pointer.json').write_bytes(encoded(old))
        (oldroot/'closed_authorization.json').write_bytes(encoded(read(AUTH)))
    else:
        require(not infrastructure_recovery and not revise_judge_cap, 'No previous trial exists')
    check_other_gates()
    validation = human.validate_labels(LABELS, 'calibration')
    packets = read(REVIEW/'calibration/packets.json')['samples']
    require(validation['complete'] == 60 and len(packets) == 60, 'Exactly 60 confirmed labels required')
    require(sum(p['generation_failed'] for p in packets) == 1, 'Expected one fixed generation failure')
    corpus = EXPERIMENT/'data/resources/corpus'
    for packet in packets:
        for ref in packet['sources']:
            path = (corpus/ref['path']).resolve()
            require(path.is_relative_to(corpus.resolve()) and sha(path.read_bytes()) == ref['file_sha256'], 'Source file drift')
            excerpt = '\n'.join(path.read_text(encoding='utf-8-sig').splitlines()[ref['line_start']-1:ref['line_end']])
            require(excerpt == ref['excerpt'] and sha(excerpt.encode()) == ref['excerpt_sha256'], 'Source excerpt drift')
    prompt = prompt_text()
    profiles = {j: public_profile(calibration_profile(j, output_cap)) for j in JUDGES}
    requests = {}
    for j in JUDGES:
        profile = calibration_profile(j, output_cap)
        require(profile['protocol'] == 'chat_completions' and not profile['stream'], 'Unsupported live profile')
        requests[j] = {}
        for p in packets:
            b = build(profile, packet_for(p), 'joint', prompt, schema())['body']
            # A conservative byte bound with framing allowance, not an exact tokenizer claim.
            require(len(json.dumps(b, ensure_ascii=False).encode())+256 <= profile['input_token_cap'],
                    'Conservative input bound exceeded')
            requests[j][p['sample_id']] = sha(encoded(b))
    manifest = dict(schema='chapter2_ai_judge_calibration_v1', prepared_utc=now(), phase='calibration',
                    authorization='负责人：用这60份已确认的人工评分开展AI裁判校准，比较两个裁判及均值；不启动验收和全量',
                    sample_ids=[p['sample_id'] for p in packets], input_files=protected_inputs(),
                    implementation={str((HERE/n).relative_to(WORK).as_posix()): sha((HERE/n).read_bytes()) for n in SOURCE_FILES},
                    profiles=profiles, request_hashes=requests, phase_contract='joint', judge_output_token_cap=output_cap,
                    prompt_sha256=sha(prompt.encode()), output_schema=schema(),
                    retry_policy=RetryPolicy().public(), concurrency={'gpt_sol': 2, 'deepseek_flash': 1},
                    generation_failure='deterministic_zero_without_API_call',
                    aggregation='mean_of_exactly_two_judges_per_answer_EAS_before_reference_error',
                    unknown_policy='no_imputation; report identified pairs and fixed-60 bounds',
                    human_reference='AI建议、真人逐项确认、助手转录；不是无AI建议的独立人评',
                    acceptance_authorized=False, full_generation_authorized=False, rubric_revisions=0,
                    previous_trial=previous,
                    design_reference=dict(path='graduation-thesis-materials/graduation-research/chapters/chapter02.md',
                        sha256=sha((WORK/'graduation-thesis-materials/graduation-research/chapters/chapter02.md').read_bytes()),stored_file='design.md'))
    ph = digest(manifest)
    root = EXPERIMENT/'release/frozen/judge_calibration'/ph
    root.mkdir(parents=True, exist_ok=False)
    stored = {}
    for i, (name, h) in enumerate(manifest['implementation'].items()):
        target = f'{i:02d}{Path(name).suffix}'
        (root/target).write_bytes((WORK/name).read_bytes()); stored[name] = target
    (root/'manifest.json').write_bytes(encoded(dict(protocol_sha256=ph, protocol=manifest, stored_implementation=stored)))
    (root/'design.md').write_bytes((WORK/manifest['design_reference']['path']).read_bytes())
    atomic(POINTER, dict(protocol_sha256=ph, frozen_manifest=(root/'manifest.json').relative_to(EXPERIMENT).as_posix(),
                         status='prepared_not_dispatched', output_root=f'evaluation/judge_calibration/{ph[:12]}'))
    out = EXPERIMENT/f'evaluation/judge_calibration/{ph[:12]}'
    (out/'packets').mkdir(parents=True)
    for p in packets:
        (out/'packets'/f"{p['sample_id']}.json").write_bytes(encoded(packet_for(p)))
    return dict(prepared=True, protocol_sha256=ph, records=60, expected_API_calls=118)


def verify(current=True):
    pointer = read(POINTER)
    frozen = read(EXPERIMENT/pointer['frozen_manifest'])
    p = frozen['protocol']; ph = pointer['protocol_sha256']
    require(digest(p) == ph == frozen['protocol_sha256'], 'Protocol digest mismatch')
    root = (EXPERIMENT/pointer['frozen_manifest']).parent
    require(sha((root/p['design_reference']['stored_file']).read_bytes()) == p['design_reference']['sha256'], 'Frozen design drift')
    for name, h in p['implementation'].items():
        require(sha((root/frozen['stored_implementation'][name]).read_bytes()) == h, 'Frozen implementation drift')
        if current:
            require(sha((WORK/name).read_bytes()) == h, 'Current implementation differs from prepared calibration')
    for name, h in p['input_files'].items():
        require(sha((WORK/name).read_bytes()) == h, 'Bound calibration input changed: '+name)
    require(p['phase'] == 'calibration' and len(p['sample_ids']) == 60, 'Wrong phase')
    check_other_gates()
    out = EXPERIMENT/pointer['output_root']
    packets = {s: read(out/'packets'/f'{s}.json') for s in p['sample_ids']}
    originals = {x['sample_id']: x for x in read(REVIEW/'calibration/packets.json')['samples']}
    for s, packet in packets.items():
        require(packet == packet_for(originals[s]), 'Anonymous packet changed')
    return ph, p, out, packets


def authorize():
    ph, p, out, packets = verify()
    atomic(AUTH, dict(schema='calibration_only_authorization_v1', protocol_sha256=ph, authorized=True,
                     phase='calibration', sample_ids=p['sample_ids'], judges=list(JUDGES), authorized_utc=now(),
                     acceptance_authorized=False, full_generation_authorized=False, source=p['authorization']))
    return dict(authorized=True, phase='calibration', protocol_sha256=ph)


def check_authorized(ph, judge, sample):
    a = read(AUTH)
    if not (a['authorized'] and a['protocol_sha256'] == ph and a['phase'] == 'calibration'
            and judge in a['judges'] and sample in a['sample_ids']
            and not a['acceptance_authorized'] and not a['full_generation_authorized']):
        raise PermissionError('Only the bound calibration cohort is authorized')


def load_deployment(judge, profile, concurrency):
    from urllib.parse import urlsplit
    from models import WORK as workspace
    project = HERE.parents[1]
    models = read(project/'config/llm/models.yaml')['models']
    provider = read(project/'config/llm/providers.yaml')['providers'][models[judge]['provider']]
    values = {}
    for filename in provider['credential_files']:
        scope, name = filename.split(':', 1)
        path = (project if scope == 'project' else workspace)/name
        if path.exists(): values.update(settings(path))
    endpoint = profile['base_url'].rstrip('/')+'/chat/completions'
    url = urlsplit(endpoint)
    require(url.scheme == 'https' and url.hostname and not url.username and not url.query, 'Invalid judge endpoint')
    return Deployment(judge, profile['model_id'], endpoint, values[profile['key_env']], concurrency)


def failure_record(packet, judge, version):
    return dict(schema_version=VERSION, sample_id=packet['sample_id'], judge_id=judge, judge_version=version,
                status='complete', points=[dict(criterion_id=c['criterion_id'], score=0) for c in packet['criteria']],
                fact_gate=0, applicability_gate=0 if packet['conditional'] else 'not_applicable',
                reason='生成失败，按预定规则固定记0；未调用AI裁判。')


def run_one(ph, protocol, out, packet, judge, profile, client):
    s = packet['sample_id']; check_authorized(ph, judge, s)
    folder = storage_path(out/judge/s); folder.mkdir(parents=True, exist_ok=True)
    target = folder/'result.json'
    with request_lock(target):
        if target.exists():
            r = read(target); require(r['protocol_sha256'] == ph, 'Existing result protocol mismatch')
            return r['status']
        if packet['generation_failed']:
            record = failure_record(packet, judge, profile['prompt_version'])
            result = dict(status='complete', origin='deterministic_generation_failure', record=record,
                          metrics=joint_metrics(record, [c['criterion_id'] for c in packet['criteria']], packet['conditional'], True))
        else:
            req = build(profile, packet, 'joint', prompt_text(), schema())
            require(sha(encoded(req['body'])) == protocol['request_hashes'][judge][s], 'Request differs from prepared body')
            check_authorized(ph, judge, s)
            raw = client.complete(req['body'], folder/'requests/000.json')
            if raw['status'] == 'response':
                try:
                    parsed = parse(profile, raw['raw_response'], packet, 'joint')
                    result = dict(status='complete', origin='AI_judge', **parsed,
                                  metrics=joint_metrics(parsed['record'], [c['criterion_id'] for c in packet['criteria']], packet['conditional']))
                except (ValueError, KeyError, TypeError) as exc:
                    result = dict(status='judge_output_failure', error_type=type(exc).__name__, error=str(exc),
                                  response_sha256=raw.get('response_sha256'), content_retried=False)
            else:
                result = dict(status='technical_unresolved', transport_status=raw['status'],
                              request_sha256=raw['request_sha256'], retry_exhausted=raw.get('retry_exhausted', False))
        result.update(protocol_sha256=ph, judge_id=judge, sample_id=s, completed_utc=now())
        atomic(target, result)
        print(json.dumps(dict(judge=judge, sample_id=s, status=result['status'], origin=result.get('origin'))), flush=True)
        return result['status']


def run(limit=None):
    ph, p, out, packets = verify()
    for j in JUDGES: check_authorized(ph, j, p['sample_ids'][0])
    pointer = read(POINTER); pointer['status'] = 'calibration_dispatch_running'; atomic(POINTER, pointer)
    def worker(judge):
        profile = calibration_profile(judge, p['judge_output_token_cap'])
        require(public_profile(profile) == p['profiles'][judge], 'Judge profile changed')
        deployment = load_deployment(judge, profile, p['concurrency'][judge])
        client = RetryingClient(deployment, RetryPolicy())
        selected = [s for s in p['sample_ids'] if not (out/judge/s/'result.json').exists()]
        if limit: selected = selected[:limit]
        with ThreadPoolExecutor(max_workers=p['concurrency'][judge]) as pool:
            return list(pool.map(lambda s: run_one(ph, p, out, packets[s], judge, profile, client), selected))
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = dict(zip(JUDGES, pool.map(worker, JUDGES)))
        return {j: dict(collections.Counter(v)) for j, v in statuses.items()}
    finally:
        a = read(AUTH); a.update(authorized=False, ended_utc=now()); atomic(AUTH, a)
        pointer = read(POINTER); pointer['status'] = 'calibration_dispatch_closed'; atomic(POINTER, pointer)


def score_known(x):
    return type(x) in (float, int) and math.isfinite(x)


def metric_bounds(m, key):
    if key in ('EAS_arith', 'EAS_geo'): return m['eas_'+key[4:]+'_bounds']
    if key == 'K': return m['coverage_bounds']
    if key == 'Strict': return m['strict_bounds']
    x = m[key]
    return [x, x] if score_known(x) else [0., 1.]


def mean_metrics(a, b):
    result = dual_eas([a, b])
    for key in ('K', 'F', 'A', 'Strict'):
        result[key] = statistics.mean([a[key], b[key]]) if all(score_known(x[key]) for x in (a, b)) else 'not_applicable' if key == 'A' and a[key] == b[key] == 'not_applicable' else None
    result['coverage_bounds'] = [statistics.mean([a['coverage_bounds'][i], b['coverage_bounds'][i]]) for i in (0, 1)]
    result['strict_bounds'] = [statistics.mean([a['strict_bounds'][i], b['strict_bounds'][i]]) for i in (0, 1)]
    for key in ('F', 'A'):
        result[key+'_bounds'] = [statistics.mean([metric_bounds(a, key)[i], metric_bounds(b, key)[i]]) for i in (0, 1)]
    return result


def comparison(rows, target, key, include_failed=True):
    applicable = [r for r in rows if (include_failed or not r['generation_failed']) and (key != 'A' or r['conditional'])]
    pairs = [(r['question_id'], r[target][key]-r['human'][key]) for r in applicable if score_known(r[target][key]) and score_known(r['human'][key])]
    low_abs = high_abs = low_diff = high_diff = 0.
    for r in applicable:
        a = metric_bounds(r['human'], key); b = r[target].get(key+'_bounds') if key in ('F', 'A') and target == 'dual_mean' else metric_bounds(r[target], key)
        lo, hi = b[0]-a[1], b[1]-a[0]
        low_abs += 0 if lo <= 0 <= hi else min(abs(lo), abs(hi)); high_abs += max(abs(lo), abs(hi))
        low_diff += lo; high_diff += hi
    n = len(applicable); errors = [d for _, d in pairs]
    return dict(full_denominator=n, identified_pairs=len(pairs), unknown_or_missing_pairs=n-len(pairs),
                mae=statistics.mean(map(abs, errors)) if errors else None,
                bias_AI_minus_human=statistics.mean(errors) if errors else None,
                rmse=math.sqrt(statistics.mean(d*d for d in errors)) if errors else None,
                exact_rate=sum(abs(d) < 1e-9 for d in errors)/len(errors) if errors else None,
                within_025_rate=sum(abs(d) <= .25+1e-9 for d in errors)/len(errors) if errors and key in ('K', 'F', 'A') else None,
                within_025_full_denominator=sum(abs(d) <= .25+1e-9 for d in errors)/n if n and key in ('K', 'F', 'A') else None,
                fixed_denominator_mae_bounds=[low_abs/n, high_abs/n] if n else None,
                fixed_denominator_bias_bounds=[low_diff/n, high_diff/n] if n else None,
                uncertainty=cluster_intervals(pairs))


def analyze():
    ph, p, out, packets = verify(current=False)
    require(not read(AUTH)['authorized'], 'Close judge dispatch before comparison')
    labels = {r['sample_id']: r['record'] for r in read(LABELS)['labels']}
    mapping = {r['sample_id']: r for r in read(REVIEW/'administration/sample_mapping.json')['samples'] if r['phase'] == 'calibration'}
    rows = []; files = {}; statuses = {j: collections.Counter() for j in JUDGES}
    usage = {j: dict(input_tokens=0, output_tokens=0, network_attempts=0, unknown_attempts=0) for j in JUDGES}
    for order, s in enumerate(p['sample_ids'], 1):
        packet = packets[s]; criteria = [c['criterion_id'] for c in packet['criteria']]
        row = dict(order=order, sample_id=s, question_id=mapping[s]['task']['id'],
                   generation_failed=packet['generation_failed'], conditional=packet['conditional'],
                   human=joint_metrics(labels[s], criteria, packet['conditional'], packet['generation_failed']), records={'human': labels[s]})
        for j in JUDGES:
            target = out/j/s/'result.json'; r = read(target)
            require(r['protocol_sha256'] == ph and r['sample_id'] == s and r['judge_id'] == j, 'Result binding mismatch')
            statuses[j][r['status']] += 1
            require(r['status'] == 'complete', 'Judge calibration incomplete; preserve failures before analysis')
            actual = joint_metrics(r['record'], criteria, packet['conditional'], packet['generation_failed'])
            require(actual == r['metrics'], 'Stored score calculation mismatch')
            row[j] = actual; row['records'][j] = r['record']
            if packet['generation_failed']:
                require(r['origin'] == 'deterministic_generation_failure' and not (target.parent/'requests').exists(), 'Failure sample must not call API')
            else:
                q = read(target.parent/'requests/000.json')
                profile = calibration_profile(j, p['judge_output_token_cap'])
                require(public_profile(profile) == p['profiles'][j], 'Profile changed')
                body = build(profile, packet, 'joint', prompt_text(), schema())['body']
                require(q['request'] == body and q['request_sha256'] == p['request_hashes'][j][s], 'Request drift or label leak')
                require(parse(profile, q['raw_response'], packet, 'joint')['record'] == r['record'], 'Parsed score drift')
                for attempt in q['attempts']:
                    ap = target.parent/'requests'/attempt['record_file']; ar = read(ap)
                    require(sha(ap.read_bytes()) == attempt['record_sha256'] and ar['request'] == body, 'Attempt drift')
                    usage[j]['network_attempts'] += ar['transport_attempts']
                    if ar['status'] == 'response':
                        wire = ap.with_suffix('.response.bin')
                        require(sha(wire.read_bytes()) == ar['response_sha256'], 'Wire response drift')
                        u = ar['raw_response']['usage']; usage[j]['input_tokens'] += u['prompt_tokens']; usage[j]['output_tokens'] += u['completion_tokens']
                    elif ar['transport_attempts']: usage[j]['unknown_attempts'] += 1
        row['dual_mean'] = mean_metrics(row[JUDGES[0]], row[JUDGES[1]])
        row['EAS_arith_differences'] = {j: row[j]['EAS_arith']-row['human']['EAS_arith'] if score_known(row[j]['EAS_arith']) and score_known(row['human']['EAS_arith']) else None for j in (*JUDGES, 'dual_mean')}
        rows.append(row)
    for path in out.rglob('*'):
        if path.is_file(): files[path.relative_to(EXPERIMENT).as_posix()] = sha(path.read_bytes())
    result = dict(schema='judge_calibration_comparison_v1', analyzed_utc=now(), protocol_sha256=ph,
                  phase='calibration_only_not_acceptance', records=60, unique_question_ids=50,
                  human_reference='ai_assisted_human_confirmed_single_reviewer', generation_failures=1,
                  statuses={j: dict(v) for j, v in statuses.items()}, usage=usage,
                  comparisons={j: {key: comparison(rows, j, key) for key in ('EAS_arith', 'EAS_geo', 'K', 'F', 'A', 'Strict')} for j in (*JUDGES, 'dual_mean')},
                  valid_answers_only={j: {key: comparison(rows, j, key, False) for key in ('EAS_arith', 'EAS_geo')} for j in (*JUDGES, 'dual_mean')},
                  point_agreement={j: ordinal_agreement([(p['score'], {x['criterion_id']: x['score'] for x in row['records'][j]['points']}[p['criterion_id']]) for row in rows for p in row['records']['human']['points']]) for j in JUDGES},
                  acceptance_started=False, full_generation_started=False, rules_frozen_for_acceptance=False,
                  implementation_snapshot=read(POINTER)['frozen_manifest'], files=files)
    folder = REVIEW/'ai_calibration'/ph[:12]; folder.mkdir(parents=True, exist_ok=True)
    for name, data in [('comparison.json', result), ('per_sample.json', dict(protocol_sha256=ph, samples=rows))]:
        path = folder/name
        require(not path.exists(), 'Never overwrite an analyzed calibration trial')
        path.write_bytes(encoded(data))
    return dict(protocol_sha256=ph, report_folder=folder.relative_to(WORK).as_posix(), comparisons=result['comparisons'], usage=usage)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['prepare', 'authorize', 'run', 'verify', 'analyze'])
    parser.add_argument('--limit-per-judge', type=int)
    parser.add_argument('--infrastructure-recovery', action='store_true')
    parser.add_argument('--revise-judge-cap', action='store_true')
    parser.add_argument('--judge-output-token-cap', type=int, choices=[2048, 8192], default=2048)
    args = parser.parse_args()
    if args.command == 'prepare': result = prepare(args.infrastructure_recovery, args.revise_judge_cap, args.judge_output_token_cap)
    elif args.command == 'authorize': result = authorize()
    elif args.command == 'run': result = run(args.limit_per_judge)
    elif args.command == 'analyze': result = analyze()
    else:
        ph, p, out, packets = verify(); result = dict(passed=True, protocol_sha256=ph, samples=len(packets))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__': main()
