"""供应商切换后的独立费用审计；代理价格未知时不推算总费用。"""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--amendment', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root, amendment = args.root.resolve(), args.amendment.resolve()
    sys.path.insert(0, str(root / 'runtime'))
    from chapter2_formal_runtime import verify, load, save, sha
    protocol, protocol_sha = verify(root, require_snapshot=False)
    config = load(amendment / 'execution_config.json')
    if sha(amendment / 'execution_config.json') != load(amendment / 'seal.json')['execution_config_sha256']:
        raise ValueError('Provider amendment drift')
    stop = load(amendment / 'stop_inventory.json')
    if sha(amendment / 'stop_inventory.json') != config['stop_audit_sha256']:
        raise ValueError('Provider boundary inventory drift')
    if args.output.exists():
        raise FileExistsError('Use a new derived output version')
    counters, records, unknown, ledger_hashes = defaultdict(Counter), {}, [], {}
    ledgers = {}
    amendments = [amendment]
    while load(amendments[-1] / 'execution_config.json').get('previous_provider_amendment'):
        previous = root / load(amendments[-1] / 'execution_config.json')['previous_provider_amendment']
        if previous in amendments:
            raise ValueError('Provider amendment cycle')
        amendments.append(previous)
    for current in amendments:
      current_sha = sha(current / 'execution_config.json')
      if current_sha != load(current / 'seal.json')['execution_config_sha256']:
        raise ValueError('Previous provider amendment drift')
      for file in (current / 'provider_attempts').glob('*.json'):
        value = load(file)
        identity = (value['request_path'], value['started_unix_ns'])
        if identity in ledgers or value['execution_amendment_sha256'] != current_sha:
            raise ValueError('Provider ledger identity/amendment drift')
        ledgers[identity] = value
        ledger_hashes[str(file.relative_to(root))] = sha(file)
    price = load(protocol['public_inputs']['price_basis']['path'])
    used_ledgers = set()
    for role, directory, names in (
        ('shared_planner', root / 'planner', {'plan.json'}),
        ('answer', root / 'answers', {'draft.json', 'final.json'}),
        ('pointwise_scoring', root / 'evaluation_only/reviews', {'review.json'}),
        ('necessary_adjudication', root / 'evaluation_only/adjudications', {'review.json'}),
    ):
        for file in sorted(directory.rglob('*.json')):
            if file.name not in names:
                continue
            value, path = load(file), str(file.relative_to(root))
            request = value['request']
            if request['model'] != protocol['model'] or request['temperature'] != 0 or request.get('enable_thinking') is not False:
                raise ValueError('Formal request model/parameters drift')
            if value.get('status') == 'response' and value['raw_response'].get('model') != protocol['model']:
                raise ValueError('Formal response model identity mismatch')
            for event in value.get('events', []):
                identity = (path, event['started_unix_ns'])
                if identity in ledgers:
                    ledger = ledgers[identity]
                    if ledger['request_sha256'] != value['request_sha256'] or ledger['endpoint'] != config['base_url'] + '/chat/completions':
                        raise ValueError('Proxy attempt request/endpoint drift')
                    if event.get('status') == 'response' and (ledger.get('status') != 'response' or ledger.get('response_model') != protocol['model'] or ledger.get('usage') != event.get('usage')):
                        raise ValueError('Proxy response usage/identity provenance mismatch')
                    provider = 'qwen_proxy'
                    used_ledgers.add(identity)
                elif path in stop['files_sha256'] and event['started_unix_ns'] <= stop['stopped_unix_ns']:
                    provider = 'official_aliyun'
                else:
                    raise ValueError('Unclassified provider attempt')
                counter = counters[provider + ':' + role]
                counter['attempts'] += 1
                counter['attempt:' + event['status']] += 1
                counter['seconds_including_pacing'] += event.get('seconds') or 0
                usage = event.get('usage')
                if usage:
                    counter['input_tokens'] += usage.get('prompt_tokens', 0)
                    counter['output_tokens'] += usage.get('completion_tokens', 0)
                else:
                    counter['unknown_usage_attempts'] += 1
                    unknown.append({'path': path, 'started_unix_ns': event['started_unix_ns'], 'provider': provider, 'status': event['status']})
            records[path] = sha(file)
    if used_ledgers != set(ledgers):
        raise ValueError('Provider ledger contains unmatched attempts')
    by_role = {}
    for role, counter in counters.items():
        cost = counter['input_tokens'] / 1e6 * price['input_cny_per_million_tokens'] + counter['output_tokens'] / 1e6 * price['output_cny_per_million_tokens'] if role.startswith('official_aliyun:') else None
        by_role[role] = {**dict(counter), 'reported_public_list_cost_lowerbound_cny': cost}
    save(args.output, {
        'schema': 'formal-mixed-provider-cost-audit-v1', 'protocol_sha256': protocol_sha,
        'analysis_implementation_sha256': sha(Path(__file__)), 'new_llm_calls': 0,
        'execution_amendment_sha256': sha(amendment / 'execution_config.json'),
        'by_provider_and_role': by_role, 'request_artifact_sha256': records,
        'provider_ledger_sha256': ledger_hashes, 'unknown_usage_attempts': unknown,
        'official_reported_public_list_cost_lowerbound_cny': sum(v['reported_public_list_cost_lowerbound_cny'] or 0 for v in by_role.values()),
        'proxy_price_cny_per_million_tokens': None, 'total_formal_cost_cny': None,
        'price_url_official_only': price['url'], 'connectivity_cost_excluded': True,
        'limits': 'Public official list price is not account bill. Proxy price unknown, total unavailable. Unknown/interrupted usage is not zero. Connectivity check and offline construction separate. Model IDs agree, upstream hosting/weight equivalence unverified.',
    })
    print(json.dumps({'status': 'derived', 'formal_requests': len(records), 'proxy_attempts': len(ledgers), 'output': str(args.output)}))


if __name__ == '__main__':
    main()
