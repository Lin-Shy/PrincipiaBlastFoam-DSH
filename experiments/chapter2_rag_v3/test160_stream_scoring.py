"""Hash-bound per-answer scoring pipeline using the frozen judge transport.

Generation is never imported/executed by this process. Both modes share two
physical request slots per judge. No grade is returned to generation.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager, ExitStack
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import threading
import time

import single_pass_dev40 as s
import test160_evaluation as evaluation
import dev40_finalize as recovery
from central_execution import Registry, exclusive_lock
from judge_contract import VERSION

BASE = s.RUN / 'test160_runs'
WRITE = threading.Lock()


def immutable(path, value):
    if path.exists():
        if s.load(path) != value:
            raise ValueError('Immutable packet drift: ' + str(path))
    else:
        s.save(path, value)


@contextmanager
def judge_slot(judge):
    folder = BASE / 'service_slots'
    folder.mkdir(exist_ok=True)
    acquired = None
    while acquired is None:
        if (BASE / ('STOP_' + judge + '.json')).exists():
            raise RuntimeError('Judge branch stopped: ' + judge)
        for slot in range(2):
            p = folder / ('%s_%d.lock' % (judge, slot))
            try:
                with p.open('x', encoding='utf-8') as f:
                    json.dump(dict(pid=os.getpid(), utc=s.now()), f)
            except FileExistsError:
                continue
            acquired = p
            break
        if acquired is None:
            time.sleep(1)
    try:
        yield
    finally:
        acquired.unlink()


def source_items(manifest, questions):
    annotations = {x['id']: x for x in s.load(s.WORKSPACE / manifest['scoring_only']['annotations'])}
    gold = s.load(s.WORKSPACE / manifest['scoring_only']['evidence'])
    items = {}
    compact = []
    for q in questions:
        a = annotations[q['id']]
        sources = []
        seen = set()
        for eid in a['required_evidence_ids']:
            e = gold[eid]
            if e['path'] in seen:
                continue
            seen.add(e['path'])
            fp = s.RUN / 'data/resources/corpus' / e['path']
            if s.sha(fp) != e['file_sha256']:
                raise ValueError('Gold source hash drift')
            text = '\n'.join('%d|%s' % (i, line) for i, line in enumerate(fp.read_text(encoding='utf-8-sig').splitlines(), 1))
            sources.append(dict(path=e['path'], file_sha256=e['file_sha256'], text=text))
        item = dict(schema_version=VERSION, sample_id='T' + '0' * 20,
                    question=q['question'], answer='', generation_failed=False,
                    criteria=[dict(criterion_id='K%03d' % (i + 1), claim=z['claim']) for i, z in enumerate(a['required_points'])],
                    conditional=a['labels']['condition_discrimination'], sources=sources)
        # Decide source whitespace representation before reading any answer or score.
        # Reserve a conservative 4096 tokenizer tokens for the 2048-token answer.
        try:
            profile, _, count = recovery.request('gpt_sol', item)
            needs_compaction = count + 4096 > profile['input_token_cap']
        except ValueError as exc:
            if 'exceeds' not in str(exc):
                raise
            needs_compaction = True
        if needs_compaction:
            compact.append(q['id'])
            for source in item['sources']:
                source['text'] = '\n'.join(z for z in source['text'].splitlines() if z.partition('|')[2].strip())
        items[q['id']] = item
    policy = dict(schema='test160_stream_source_representation', manifest_sha256=s.sha(evaluation.runner.MANIFEST),
                  whitespace_compacted_question_ids=sorted(compact),
                  rule='Full required sources with original line numbers; remove blank numbered lines for all methods/modes of a question if source-only input plus 4096 answer reserve exceeds frozen input cap. No substantive line removed.',
                  decision_uses_answers=False, decision_uses_scores=False)
    immutable(BASE / 'scoring/source_policy.json', policy)
    return items


def run(authorization, mode):
    manifest, questions = evaluation.authorize(authorization, mode)
    recovery.dc.guard_operational()
    out = BASE if mode == 'agentic' else BASE / 'supplement/single_pass'
    out.mkdir(parents=True, exist_ok=True)
    s.OUT = out
    recovery.RETRY_INVALID = True
    expected = 4160 if mode == 'agentic' else 960
    immutable(out / 'protocol.json', dict(schema='test160_dual_scoring', scope=dict(generation_sessions=expected),
              test_manifest_sha256=s.sha(evaluation.runner.MANIFEST), test160=True, execution_mode=mode))
    with exclusive_lock(out / 'stream_scoring.lock'):
        templates = source_items(manifest, questions)
        configs = [c for c in manifest['configurations'] if mode == 'agentic' or c['method_id'] in ('graph', 'bm25', 'bge_m3')]
        rows = {}
        registry = Registry()
        finished = {}
        active = {}
        errors = {}

        def job(row, judge):
            item = row['item']
            root = out / 'scoring' / judge / item['sample_id']
            if item['generation_failed']:
                return 'generation_failure_zero'
            try:
                recovery.request(judge, item)
            except ValueError as exc:
                if 'exceeds' not in str(exc):
                    raise
                immutable(root / 'input_hold.json', dict(status='not_sent_input_budget', generation_sha256=row['generation_sha256']))
                return 'not_sent_input_budget'
            while True:
                if (BASE / ('STOP_' + judge + '.json')).exists():
                    return 'branch_held'
                state = recovery.reconcile(root, judge, item)
                if state != 'pending':
                    return state
                ordinal = len(list((root / 'recovery').glob('attempt_*'))) + 1
                if ordinal > 1:
                    time.sleep([5, 20][min(ordinal - 2, 1)])
                with judge_slot(judge):
                    # Slot covers the complete physical request; modes cannot exceed 2.
                    result = recovery.attempt(root, judge, item, ordinal, registry)
                reason = result.get('reason', '')
                if reason in ('model_identity_mismatch', 'usage_unknown_stop_and_reconcile'):
                    immutable(BASE / ('STOP_' + judge + '.json'), dict(status=reason, sample_id=item['sample_id'], utc=s.now()))
                # Reconciliation alone decides finite retry / invalid / uncertain hold.

        # Independent judge pools prevent slow Sol jobs from occupying all
        # worker threads while waiting for Sol's two physical request slots.
        with ExitStack() as stack:
            pools = {j:stack.enter_context(ThreadPoolExecutor(max_workers=2)) for j in s.JUDGES}
            while True:
                draining = (out/'DRAIN_stream_scoring.json').exists()
                if draining:
                    for future in list(active):
                        if future.cancel():active.pop(future)
                for future in list(active):
                    if not future.done():
                        continue
                    key = active.pop(future)
                    try:
                        finished[key] = future.result()
                    except Exception as exc:
                        errors['|'.join(key)] = dict(error_type=type(exc).__name__, message=str(exc)[:500])
                        finished[key] = 'infrastructure_hold'
                    print(json.dumps(dict(mode=mode, judge=key[1], sample_id=key[0], status=finished[key])), flush=True)
                if draining and not active:
                    s.save(out/'scoring/drained.json',dict(utc=s.now(),pid=os.getpid(),in_flight=0,requests_resent=False))
                    return
                # Register each completed generation once, binding bytes before submission.
                for c in configs:
                    for q in questions:
                        key = (c['config_id'], q['id'])
                        if key in rows:
                            continue
                        fp = out / 'generation' / c['config_id'] / q['id'] / 'result.json'
                        if not fp.exists():
                            continue
                        try:
                            raw = s.load(fp)
                        except (OSError, json.JSONDecodeError):
                            continue
                        if raw.get('manifest_sha256') != s.sha(evaluation.runner.MANIFEST):
                            raise ValueError('Generation manifest mismatch')
                        sha = s.sha(fp)
                        item = deepcopy(templates[q['id']])
                        item.update(sample_id='T' + hashlib.sha256((c['config_id']+'|'+q['id']+'|'+sha).encode()).hexdigest()[:20],
                                    answer=raw.get('answer') or '', generation_failed=raw['status'] != 'answered')
                        row = dict(model=c['logical_model'], method=c['method_id'], qid=q['id'], item=item,
                                   generation_file=fp.relative_to(s.RUN).as_posix(), generation_sha256=sha)
                        immutable(out / 'scoring/packets' / c['config_id'] / (q['id']+'.json'), row)
                        rows[key] = row
                active_keys = set(active.values())
                for row in ([] if draining else rows.values()):
                    for judge in s.JUDGES:
                        key = (row['item']['sample_id'], judge)
                        if key not in finished and key not in active_keys:
                            active[pools[judge].submit(job, row, judge)] = key
                from collections import Counter
                with WRITE:
                    s.save(out / 'scoring/stream_status.json', dict(utc=s.now(), pid=os.getpid(), mode=mode,
                           expected_answers=expected, bound_answers=len(rows), completed_evaluations=len(finished),
                           states=dict(Counter(finished.values())), errors=errors,
                           active_or_queued=len(active), manifest_sha256=s.sha(evaluation.runner.MANIFEST)))
                if len(rows) == expected and not active:
                    packet = dict(count=expected, items=[rows[c['config_id'], q['id']] for c in configs for q in questions],
                                  protocol_sha256=s.sha(out/'protocol.json'),
                                  whitespace_compacted_question_ids=s.load(BASE/'scoring/source_policy.json')['whitespace_compacted_question_ids'])
                    immutable(out / 'scoring/packet.json', packet)
                    return
                time.sleep(5)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--authorization', type=Path, required=True)
    p.add_argument('--mode', choices=['agentic', 'single_pass'], default='agentic')
    a = p.parse_args()
    run(a.authorization, a.mode)
