"""统一总榜的完整会话网格、真实调用账目和方法盲化审阅包。无模型调用。"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import statistics


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def percentile(values, p):
    if not values:
        return None
    values = sorted(values)
    position = (len(values)-1)*p
    lo = int(position)
    hi = min(len(values)-1, lo+1)
    return values[lo] + (values[hi]-values[lo])*(position-lo)


def verify(root):
    protocol = read(root / "protocol.json")
    for name, expected in protocol["files"].items():
        if sha(root / name) != expected:
            raise ValueError("frozen artifact changed: " + name)
    return protocol


def ledger(folder):
    # QA, semantic construction and review share the same attempt ledger schema.
    requests = [p for p in folder.glob("*.json") if "request_sha256" in read(p)]
    usage, statuses, models, fingerprints = Counter(), Counter(), Counter(), Counter()
    unknown = 0
    for path in requests:
        value = read(path)
        response = value.get("raw_response", {})
        if response:
            models[response.get("model", "unknown")] += 1
            fingerprints[response.get("system_fingerprint") or "not_reported"] += 1
        for attempt in value.get("events", []):
            statuses[attempt["status"]] += 1
            tokens = attempt.get("usage")
            if tokens is None and attempt["status"] == "response":
                tokens = response.get("usage")
            if not isinstance(tokens, dict) or "total_tokens" not in tokens:
                unknown += 1
            if isinstance(tokens, dict):
                for key in ("prompt_tokens", "completion_tokens", "total_tokens", "prompt_cache_hit_tokens", "prompt_cache_miss_tokens"):
                    if key in tokens:
                        usage[key] += tokens[key]
    invocations = [read(p) for p in (folder / "invocations").glob("*.json")]
    timed = [v.get("elapsed_seconds") for v in invocations if not v.get("replay")]
    duration = sum(timed) if timed and all(isinstance(t, (int, float)) for t in timed) else None
    return {"reported_usage": dict(usage), "unknown_usage_attempts": unknown, "attempt_statuses": dict(statuses),
            "provider_models": dict(models), "provider_fingerprints": dict(fingerprints), "session_seconds": duration,
            "actual_total_tokens": usage.get("total_tokens") if requests and not unknown else None,
            "actual_currency_cost": None}


def audit(root, output):
    protocol = verify(root)
    anchor = next(iter(protocol["groups"]))
    questions = read(root / anchor / "questions.json")
    arms, all_sessions = [], []
    for group, methods in protocol["groups"].items():
        expected = set()
        for method in methods:
            rows = []
            for q in questions:
                for rep in range(1, protocol["replicates"]+1):
                    name = f"{q['id']}--{method}--r{rep}"
                    expected.add(name)
                    folder = root / group / "sessions" / name
                    result_path = folder / "result.json"
                    result = read(result_path) if result_path.exists() else None
                    if result is not None:
                        if (result['id'], result['item_id'], result['method'], result['replicate'], result['question']) != (q['id'],q['item_id'],method,rep,q['question']):
                            raise ValueError("result identity mismatch: " + name)
                        if result['returned_characters'] > 24000 or any(e.get('returned_characters',0)>6000 for e in result['events']):
                            raise ValueError("public budget exceeded: " + name)
                    row = {"arm": group, "method": method, "session": name, "family": q['item_id'],
                           "status": result['status'] if result else 'attempted_no_answer' if folder.exists() else 'not_run',
                           "answer_sha256": sha(result_path) if result else None, "quality_reviewed": False,
                           "strict_success": None, **ledger(folder)}
                    rows.append(row)
                    all_sessions.append(row)
            cost = Counter()
            for row in rows:
                cost.update(row['reported_usage'])
            latency = [r['session_seconds'] for r in rows if r['session_seconds'] is not None]
            arms.append({"arm":group,"method":method,"expected":len(rows),
                         "statuses":dict(Counter(r['status'] for r in rows)), "ranking_status":"unreviewed_incomplete",
                         "strict_success":None,"citation_accuracy":None,"cross_source_completeness":None,
                         "reported_usage":dict(cost), "unknown_usage_attempts":sum(r['unknown_usage_attempts'] for r in rows),
                         "latency_p50_seconds":percentile(latency,.5),"latency_p95_seconds":percentile(latency,.95),
                         "latency_measured_sessions":len(latency),"actual_currency_cost":None})
        extras = {p.name for p in (root/group/'sessions').glob('*') if p.is_dir()} - expected
        if extras:
            raise ValueError("out-of-protocol sessions: " + repr(sorted(extras)))
    result = {"schema":"leaderboard-audit-v1","protocol_sha256":sha(root/'protocol.json'),"arms":arms,"sessions":all_sessions,
              "note":"Unreviewed or unrun scores are null. Failed requests remain in cost ledger. No historical quality scores imported. Initialization, construction and review costs require separate ledgers."}
    save(output,result)
    return result


def packets(root, output):
    """Gold 只进入独立评分包；不写入作答请求或图。盲化包不暴露方法/轨迹。"""
    protocol = verify(root)
    protocol_sha = sha(root/'protocol.json')
    mapping = {}
    anchor = next(iter(protocol['groups']))
    rules = read(root/anchor/'evaluation_only/scoring-rules.json')
    annotations = {a['id']: a for a in read(root/anchor/'evaluation_only/annotations.json')}
    for group, methods in protocol['groups'].items():
        for path in sorted((root/group/'sessions').glob('*/result.json')):
            r = read(path)
            opaque = hashlib.sha256((protocol_sha + ':' + group + '/' + path.parent.name).encode()).hexdigest()[:24]
            public = {"blind_id":opaque,"question":r['question'],"answer":r['parsed_answer'],
                      "annotation":annotations[r['item_id']],"rules":rules,"actually_seen_original_lines":r['seen_lines'],
                      "review_requirements":"Review each gold point, each cited claim and extra factual assertions against original sources. Correct coordinates do not establish semantic support. Full credit requires answer-agent-visible support. Do not infer absence from failed search. Judge scope, roles, conditions, instance/default distinction and both sources. Record uncertainty and disagreements; no automatic keyword scoring."}
            destination=output/'packets'/f'{opaque}.json'
            if destination.exists() and read(destination)!=public:
                raise ValueError('changed review packet')
            save(destination,public)
            mapping[opaque]={"arm":group,"session":path.parent.name,"result_sha256":sha(path),"packet_sha256":sha(destination),"protocol_sha256":protocol_sha}
    save(output/'evaluation_only/blind-map.json',mapping)
    return len(mapping)


if __name__=='__main__':
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('command',choices=['audit','packets'])
    cli.add_argument('--run',type=Path,required=True)
    cli.add_argument('--output',type=Path,required=True)
    args=cli.parse_args()
    if args.command=='audit':
        result=audit(args.run,args.output)
        print(json.dumps({'arms':len(result['arms']),'sessions':len(result['sessions']),'scores':'unreviewed'},ensure_ascii=False))
    else:
        print(json.dumps({'blinded_packets':packets(args.run,args.output)}))
