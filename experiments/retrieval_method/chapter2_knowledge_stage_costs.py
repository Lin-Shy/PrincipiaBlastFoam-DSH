"""Reconcile all archived physical model attempts for the new QA activity.

Counts immutable physical events, including discarded development revisions,
source-authoring copies, failed calls and response reuse. This is an API cost
ledger, not an inference of unrecorded CPU/GPU time or a monetary bill.
"""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import time

OFFLINE_ENDPOINT = 'https://api.deepseek.com/chat/completions'


def read(path): return json.loads(path.read_text(encoding='utf-8'))
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def canonical(value): return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def stage_for(relative):
    parts = Path(relative).parts; first = parts[0]; second = parts[1] if len(parts) > 1 else ''
    if first in {'authoring', 'reviews'}: return 'dataset_design'
    if first == 'setup' and second.startswith('graph_'): return 'cold_graph_construction'
    if first == 'audit' and second.startswith(('transport_recovery_', 'provider_field_probe_', 'registered8_availability_')):
        return 'connectivity_diagnostics'
    if first == 'development':
        if second.startswith(('connectivity_', 'scoring_connectivity_')): return 'connectivity_diagnostics'
        if second.startswith('pilot_matrix_'): return 'main_method_development'
        if second.startswith('ablation_pilot_'): return 'ablation_development'
        if second.startswith('score_controls_'): return 'scoring_control_construction'
        if second.startswith(('score_calibration_', 'actual_answer_scoring_')): return 'primary_scoring_development'
        if second.startswith('citation_calibration_'): return 'citation_scoring_development'
    if first == 'formal_generation': return 'formal_generation'
    if first in {'formal_grading', 'formal_scores'}: return 'formal_primary_grading'
    if first == 'formal_citations': return 'formal_citation_grading'
    raise ValueError('unclassified physical request archive: ' + str(relative))


def event_rows(path, root):
    # Live ledgers are atomically replaced. Bind parsed events and the file
    # fingerprint to the same read, rather than hashing a later replacement.
    captured = path.read_bytes()
    record = json.loads(captured)
    if not isinstance(record, dict) or not isinstance(record.get('request'), dict) or 'request_sha256' not in record:
        return None
    body = record['request']; model = body.get('model')
    if not isinstance(model, str): raise ValueError('physical request model absent')
    serializations = [json.dumps(body, ensure_ascii=False, sort_keys=s, separators=(',', ':'), allow_nan=False).encode('utf-8')
                      for s in (False, True)]
    if record['request_sha256'] not in [hashlib.sha256(v).hexdigest() for v in serializations]:
        raise ValueError('persisted physical request body/hash mismatch: ' + str(path))
    events = record.get('events')
    if not isinstance(events, list): raise ValueError('physical event ledger absent')
    endpoint = record.get('endpoint'); inferred = endpoint is None
    if inferred:
        if model != 'deepseek-flash': raise ValueError('only fixed offline DeepSeek endpoint may be inferred')
        endpoint = OFFLINE_ENDPOINT
    if not isinstance(endpoint, str) or not endpoint.startswith('https://'): raise ValueError('invalid API endpoint')
    relative = path.relative_to(root).as_posix(); stage = stage_for(relative)
    output = []
    for event in events:
        if (not isinstance(event, dict) or type(event.get('attempt')) is not int or event['attempt'] < 1
                or type(event.get('started_unix')) not in (int, float) or not math.isfinite(event['started_unix'])):
            raise ValueError('physical attempt identity invalid')
        seconds = event.get('seconds')
        if event.get('status') != 'in_flight' and (type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds < 0):
            raise ValueError('physical request terminal duration absent or invalid')
        identity = (endpoint, model, record['request_sha256'], event['attempt'], event['started_unix'])
        output.append((identity, event))
    return {'path': relative, 'sha256': hashlib.sha256(captured).hexdigest(), 'stage': stage, 'subphase': '/'.join(Path(relative).parts[:2]),
            'model': model, 'endpoint': endpoint, 'endpoint_inferred_from_fixed_offline_client': inferred,
            'request_sha256': record['request_sha256'], 'status': record['status'], 'events': output,
            'is_curated_copy': 'raw_response_path_relative_to_authoring' in record}


def empty_totals():
    return {'physical_attempts': 0, 'usage_known_attempts': 0, 'usage_unknown_attempts': 0,
            'known_prompt_tokens': 0, 'known_completion_tokens': 0, 'known_total_tokens': 0,
            'sum_known_physical_request_seconds': 0.0, 'duration_unknown_attempts': 0,
            'unresolved_attempt_starts': 0, 'physical_status_counts': {}, 'models': {}}


def add_event(totals, model, event):
    totals['physical_attempts'] += 1; usage = event.get('usage')
    known = isinstance(usage, dict) and all(type(usage.get(k)) is int and usage[k] >= 0 for k in ('prompt_tokens', 'completion_tokens'))
    totals['usage_known_attempts' if known else 'usage_unknown_attempts'] += 1
    if known:
        totals['known_prompt_tokens'] += usage['prompt_tokens']; totals['known_completion_tokens'] += usage['completion_tokens']
        totals['known_total_tokens'] += usage['prompt_tokens'] + usage['completion_tokens']
    if event.get('status') == 'in_flight':
        totals['unresolved_attempt_starts'] += 1; totals['duration_unknown_attempts'] += 1
    else: totals['sum_known_physical_request_seconds'] += event['seconds']
    for field, key in [('physical_status_counts', event.get('status', 'missing')), ('models', model)]:
        totals[field][key] = totals[field].get(key, 0) + 1


def reconcile(root):
    started = time.time()
    records = []
    for path in sorted(root.rglob('*.json')):
        parts = path.relative_to(root).parts
        if 'runtime' in parts or 'accepted_measurement' in parts or 'evaluation_only' in parts: continue
        # Gold and source/score opinions are not API ledgers. They must not be
        # opened by the cost collector, including an incomplete source copy.
        if parts[0] in {'formal_original_review', 'formal_citation_review', 'formal_analysis'}: continue
        if parts[0] == 'audit' and len(parts) > 1 and parts[1].startswith('stage_costs_'): continue
        # Registered activity API ledgers all live in requests/responses.
        # Select paths before parsing so score labels and answer JSON never load.
        if not any(part in {'requests', 'responses'} for part in parts): continue
        row = event_rows(path, root)
        if row is not None: records.append(row)
    # Prefer an original response over its authoring curation; early calibration
    # paths precede later deterministic response copies. Event identity handles
    # resumed records with a copied prefix and new physical attempts.
    records.sort(key=lambda r: (r['is_curated_copy'], r['path'].startswith('audit/'), r['path']))
    seen = {}; duplicate_events = 0; stages = {}; subphases = {}; grand = empty_totals(); origins = []
    for r in records:
        new = reused = 0
        for identity, event in r['events']:
            if identity in seen:
                old = seen[identity]
                if canonical(old['event']) != canonical(event):
                    # A stale persisted in-flight prefix may have a later bound
                    # terminal copy. Never invent a response for an unmatched
                    # interrupted attempt, and never recharge copied retries.
                    earlier, later = (old['event'], event) if old['event'].get('status') == 'in_flight' else (event, old['event'])
                    if earlier.get('status') != 'in_flight' or any(k != 'status' and later.get(k) != v for k, v in earlier.items()):
                        raise ValueError('conflicting persisted copies of one physical attempt')
                    if event.get('status') != 'in_flight': old['event'] = event
                duplicate_events += 1; reused += 1; continue
            seen[identity] = {'event': event, 'stage': r['stage'], 'subphase': r['subphase'], 'model': r['model'], 'path': r['path']}; new += 1
        origins.append({k: v for k, v in r.items() if k not in {'events', 'is_curated_copy'}} | {
            'new_physical_attempts': new, 'reused_physical_attempts': reused})
    for origin in seen.values():
        for target in (grand, stages.setdefault(origin['stage'], empty_totals()), subphases.setdefault(origin['subphase'], empty_totals())):
            add_event(target, origin['model'], origin['event'])
    planned_stages = ('dataset_design', 'cold_graph_construction', 'scoring_control_construction', 'connectivity_diagnostics',
        'main_method_development', 'ablation_development', 'primary_scoring_development', 'citation_scoring_development',
        'formal_generation', 'formal_primary_grading', 'formal_citation_grading')
    for stage in planned_stages: stages.setdefault(stage, empty_totals())
    # Retain only accounting metadata for a verifiable immutable observation.
    # No prompt, response, answer, source opinion, or grading label is exported.
    physical_snapshot = []
    for identity, origin in seen.items():
        endpoint, model, request_sha256, attempt, started_unix = identity
        event = origin['event']
        physical_snapshot.append({'endpoint': endpoint, 'model': model,
            'request_sha256': request_sha256, 'attempt': attempt, 'started_unix': started_unix,
            'stage': origin['stage'], 'subphase': origin['subphase'], 'origin_path': origin['path'],
            'event': {k: event[k] for k in ('status', 'seconds', 'usage', 'code') if k in event}})
    return {'schema': 'knowledge_qa_all_stage_physical_model_costs_v1', 'formal_result': False,
        'observed_started_unix': started, 'observed_finished_unix': time.time(),
        'request_binding_rule': 'Each hash binds exactly the bytes parsed at observation; live ledgers may subsequently be atomically replaced.',
        'gold_and_source_or_score_opinion_files_opened': False,
        'ledger_path_rule': 'Only JSON files under requests/responses directories, excluding private/frozen-copy roots; score/result/opinion JSON is never parsed.',
        'stages': stages, 'subphases': subphases, 'grand_total': grand, 'request_record_files': len(records),
        'physical_event_snapshot': physical_snapshot,
        'duplicate_physical_events_not_recharged': duplicate_events, 'request_bindings': origins,
        'physical_event_identity': ['endpoint', 'model', 'request_sha256', 'attempt', 'started_unix'],
        'unknown_usage_not_zero': True, 'discarded_invalid_and_failed_revisions_included': True,
        'interrupted_attempt_rule': 'Unmatched persisted in-flight starts are unresolved, with unknown charge/usage/duration. No fabricated terminal outcome; recorded start does not prove provider processing.',
        'duplicate_origin_rule': 'Original development/authoring ledgers precede audit recovery copies; copied prefixes retain original stage, newly appended attempts retain recovery stage.',
        'money_cost': None, 'money_cost_reason': 'No frozen provider tariff or invoice.',
        'offline_endpoint_inference': 'Legacy exact deepseek-flash ledgers omit endpoint; their frozen client uses https://api.deepseek.com/chat/completions.',
        'wall_time_scope': 'Sum of recorded physical HTTP attempt durations, including failures; excludes retry waits and local preprocessing. Parallel durations are not elapsed project time.',
        'local_compute_cost': None, 'local_compute_reason': 'No complete CPU/GPU meter for tokenization, E5 embedding/indexing, deterministic graph compilation or source review.',
        'scope': 'Only this new QA activity. Historical grep activities and unrelated chapters excluded. Empty formal stages mean not run, not a measured free formal experiment.'}


def main():
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('--activity', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True); a = p.parse_args()
    if a.output.exists(): raise FileExistsError('new immutable stage-cost report required')
    report = reconcile(a.activity.resolve()); report['collector_sha256'] = sha(Path(__file__))
    a.output.parent.mkdir(parents=True, exist_ok=True); a.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print({k: report[k] for k in ('request_record_files', 'duplicate_physical_events_not_recharged', 'grand_total')})


if __name__ == '__main__': main()
