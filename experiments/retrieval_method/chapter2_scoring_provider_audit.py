"""评分供应商构成与结构错误审计；只读冻结输出，不改变质量评分或样本。"""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--partial', action='store_true')
    args = parser.parse_args()
    root = args.root.resolve()
    sys.path.insert(0, str(root / 'runtime'))
    from chapter2_formal_runtime import verify, load, save, sha
    protocol, protocol_sha = verify(root, require_snapshot=False)
    if args.output.exists():
        raise FileExistsError('New audit version required')
    manifest_file = root / 'evaluation_only/review_jobs.json'
    identity_file = root / 'evaluation_only/identity.json'
    manifest, identity = load(manifest_file), load(identity_file)
    if manifest['protocol_sha256'] != protocol_sha or manifest['identity_sha256'] != sha(identity_file):
        raise ValueError('Frozen blind manifest drift')
    boundary = root / 'execution_amendments/provider_proxy_001/stop_inventory.json'
    stop = load(boundary)
    # 先捕获已经落盘且不再更改的compiled集合，随后读取其已闭合ledger。
    # 避免在线进程推进时将新响应与先前的in_flight快照配对。
    selected_records = {file for stage in ['reviews', 'adjudications']
                        for file in (root / 'evaluation_only' / stage).rglob('compiled.json')}
    ledger = {}
    ledger_hashes = {}
    for amendment in sorted((root / 'execution_amendments').glob('provider_proxy_*')):
        config_sha = sha(amendment / 'execution_config.json')
        if load(amendment / 'seal.json')['execution_config_sha256'] != config_sha:
            raise ValueError('Provider seal drift')
        for file in (amendment / 'provider_attempts').glob('*.json'):
            value = load(file)
            if value['execution_amendment_sha256'] != config_sha:
                raise ValueError('Provider ledger drift')
            key = (value['request_path'], value['started_unix_ns'])
            if key in ledger:
                raise ValueError('Duplicate provider event')
            ledger[key] = value
            ledger_hashes[str(file.relative_to(root))] = sha(file)
    counts, statuses, errors, records = defaultdict(Counter), defaultdict(Counter), defaultdict(Counter), {}
    session_providers = defaultdict(set)
    rows = []
    missing = []
    for key, job in manifest['jobs'].items():
        blind = job['blind_id']
        item = identity[blind]
        for stage in ['reviews', 'adjudications']:
            file = root / 'evaluation_only' / stage / key / 'compiled.json'
            if file not in selected_records:
                if stage == 'reviews':
                    missing.append(key)
                continue
            compiled = load(file)
            response_file = file.parent / 'review.json'
            if compiled['protocol_sha256'] != protocol_sha or compiled['packet_sha256'] != job['packet_sha256'] or compiled['response_sha256'] != sha(response_file):
                raise ValueError('Frozen scoring input/response drift')
            response = load(response_file)
            if response['request']['model'] != protocol['model'] or response['raw_response'].get('model') != protocol['model']:
                raise ValueError('Scoring model identity drift')
            winners = [e for e in response['events'] if e['status'] == 'response']
            if len(winners) != 1:
                raise ValueError('Expected exactly one received response')
            event = winners[0]
            path = str(response_file.relative_to(root))
            event_key = (path, event['started_unix_ns'])
            if event_key in ledger:
                supplier = 'qwen_proxy'
                if ledger[event_key].get('response_model') != protocol['model'] or ledger[event_key].get('usage') != event.get('usage'):
                    raise ValueError('Proxy response identity/usage drift')
            elif path in stop['files_sha256'] and event['started_unix_ns'] <= stop['stopped_unix_ns']:
                supplier = 'official_aliyun'
            else:
                raise ValueError('Unclassified scoring response provider')
            arm = item['arm']
            counts[stage + ':' + arm][supplier + ':' + job['kind']] += 1
            statuses[stage + ':' + supplier][compiled['status']] += 1
            if compiled['status'] != 'valid_structure':
                errors[stage + ':' + supplier][compiled.get('error', 'unknown')] += 1
            if stage == 'reviews':
                session_providers[blind].add(supplier)
            rows.append({'key': key, 'blind_id': blind, 'arm': arm, 'category': item['category'],
                         'kind': job['kind'], 'stage': stage, 'provider': supplier,
                         'structure_status': compiled['status'], 'response_model': response['raw_response']['model']})
            records[str(file.relative_to(root))] = sha(file)
            records[path] = sha(response_file)
    if missing and not args.partial:
        raise ValueError('First reviews incomplete; explicit partial audit required')
    if not args.partial and not all((root / 'completion' / ('adjudication--' + str(s) + '.json')).exists() for s in range(protocol['scoring_shards'])):
        raise ValueError('Registered adjudication barrier incomplete')
    sessions = Counter()
    for blind, providers in session_providers.items():
        sessions[identity[blind]['arm'] + ':' + '+'.join(sorted(providers))] += 1
    save(args.output, {'schema': 'scoring-provider-composition-v1', 'protocol_sha256': protocol_sha,
        'analysis_implementation_sha256': sha(Path(__file__)), 'new_llm_calls': 0,
        'partial': bool(args.partial), 'planned_first_reviews': len(manifest['jobs']), 'missing_first_reviews': missing,
        'by_stage_arm_provider_kind': {k: dict(v) for k, v in counts.items()},
        'structure_by_stage_provider': {k: dict(v) for k, v in statuses.items()},
        'structure_errors_by_stage_provider': {k: dict(v) for k, v in errors.items()},
        'first_review_session_provider_sets_by_arm': dict(sessions), 'rows': rows,
        'record_sha256': records, 'provider_ledger_sha256': ledger_hashes,
        'manifest_sha256': sha(manifest_file), 'identity_sha256': sha(identity_file), 'provider_boundary_sha256': sha(boundary),
        'limits': 'Provider changed after user quota exhaustion, not randomized treatment. Blind sessions were seed-shuffled before scoring. Structural validity is not semantic truth. Same model IDs do not verify internal weight/hosting equivalence. No provider-specific regeneration or score correction.',
    })
    print(json.dumps({'received_scoring_records': len(rows), 'missing_first_reviews': len(missing), 'partial': bool(args.partial)}))


if __name__ == '__main__':
    main()
