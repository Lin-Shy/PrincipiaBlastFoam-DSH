"""汇总已经闭合的正式规划与回答成本，进行中评分不混入这些分母。"""
import argparse
from collections import Counter
import json
from pathlib import Path
import statistics
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    sys.path.insert(0, str(root / 'runtime'))
    from chapter2_formal_runtime import verify, load, sha, jobs, ANSWER_ARMS
    protocol, protocol_sha = verify(root, require_snapshot=False)
    for name in ['planner--shared'] + ['answer--'+a for a in ANSWER_ARMS]:
        if not (root / 'completion' / (name+'.json')).exists():
            raise ValueError('规划与全部回答阶段必须完整闭合')
    if args.output.exists():
        raise FileExistsError('new closed-phase cost version required')
    price_path = Path(protocol['public_inputs']['price_basis']['path'])
    if sha(price_path) != protocol['public_inputs']['price_basis']['sha256']:
        raise ValueError('冻结价格快照变化')
    price = load(price_path)
    files = {'shared_planner': [], **{a: [] for a in ANSWER_ARMS}}
    for key, _, _ in jobs(protocol):
        files['shared_planner'].append(root / 'planner' / key / 'plan.json')
        for arm in ANSWER_ARMS:
            files[arm].extend(root / 'answers' / arm / key / (n+'.json') for n in ['draft', 'final'])
    rows, hashes, missing_usage = {}, {}, []
    for role, paths in files.items():
        counts, seconds, starts, ends = Counter(), [], [], []
        for file in paths:
            data = load(file)
            request = data['request']
            if request['model'] != protocol['model'] or request['temperature'] != 0 or request['enable_thinking'] is not False:
                raise ValueError('在线模型或生成参数变化')
            if request['max_tokens'] != (700 if role == 'shared_planner' else 2400):
                raise ValueError('输出预算变化')
            if data['status'] != 'response' or data['raw_response']['model'] != protocol['model']:
                raise ValueError('闭合角色缺少同名有效响应')
            counts['requests'] += 1
            for event in data['events']:
                counts['attempts'] += 1
                counts['attempt:'+event['status']] += 1
                if event.get('seconds') is not None:
                    seconds.append(event['seconds'])
                    ends.append(event['started_unix_ns']/1e9+event['seconds'])
                starts.append(event['started_unix_ns']/1e9)
                usage = event.get('usage')
                if usage is None:
                    counts['unknown_usage_attempts'] += 1
                    missing_usage.append({'file': str(file.relative_to(root)), 'status': event['status'], 'http_status': event.get('http_status')})
                else:
                    counts['input_tokens'] += usage['prompt_tokens']
                    counts['output_tokens'] += usage['completion_tokens']
            hashes[str(file.relative_to(root))] = sha(file)
        cost = counts['input_tokens']/1e6*price['input_cny_per_million_tokens']+counts['output_tokens']/1e6*price['output_cny_per_million_tokens']
        rows[role] = {**dict(counts), 'reported_public_list_cost_lowerbound_cny': cost,
                      'sum_attempt_elapsed_seconds_including_pacing': sum(seconds),
                      'median_observed_attempt_seconds': statistics.median(seconds),
                      'observed_first_start_to_last_end_seconds': max(ends)-min(starts)}
    if len(hashes) != 288+3456:
        raise ValueError('闭合调用分母变化')
    output = {'schema': 'formal-closed-planning-answer-costs-v1', 'protocol_sha256': protocol_sha,
              'script_sha256': sha(Path(__file__)), 'price_snapshot_sha256': sha(price_path),
              'price_url': price['url'], 'by_role': rows, 'request_artifact_sha256': hashes,
              'unknown_usage_attempts': missing_usage, 'completed_requests': len(hashes),
              'reported_public_list_cost_lowerbound_cny': sum(r['reported_public_list_cost_lowerbound_cny'] for r in rows.values()),
              'new_llm_calls': 0, 'limits': 'closed planning288 and answer3456requests only; grading/adjudication and offline construction excluded; recordedusage publicBeijing listprice, not accountbill; unknownattempt consumption notzero; attempts include sharedquota waiting, not puremodel latency; role elapsedoverlap prevents adding as walltime'}
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({'requests': len(hashes), 'cost_lowerbound_cny': output['reported_public_list_cost_lowerbound_cny'], 'unknown_attempts': len(missing_usage)}))


if __name__ == '__main__':
    main()
