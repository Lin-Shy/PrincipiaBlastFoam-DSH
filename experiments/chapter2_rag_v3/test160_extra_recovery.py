"""Explicit owner-approved recovery epoch; immutable original requests and grades.

This epoch alone may reissue reviewed unresolved requests or exceed old attempt
limits. At most two additional physical calls per reviewed answer/judge, 2540
overall. First valid response wins. There is no score-based selection.
"""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
import json
from pathlib import Path
import os
import threading
import time

import test160_resume_scores as old
from central_execution import Registry, exclusive_lock
from judge_api_adapter import digest

BASE = old.BASE
EPOCH = 'extra_recovery_20261102'
AUTH = BASE / 'extra_recovery_authorization_20261102.json'
PLAN = BASE / 'remaining_recovery_review_20261102.csv'
STATE = BASE / EPOCH
ORIGINAL_REQUEST = old.rec.request
APPROVED = set()
WRITE = threading.Lock()


def allowed_authorization():
    a = old.read(AUTH)
    assert a['owner_confirmed'] and a['epoch'] == EPOCH
    assert a['manifest_sha256'] == old.s.sha(old.ev.runner.MANIFEST)
    assert a['reviewed_plan_sha256'] == old.s.sha(PLAN)
    assert a['max_physical_requests'] == 2540 and a['max_additional_calls_per_judging_task'] == 2
    assert a['unresolved_prior_requests_may_be_reissued']
    rows = list(csv.DictReader(PLAN.open(encoding='utf-8-sig')))
    assert len(rows) == a['reviewed_judging_tasks'] == 1270
    assert len({(r['judge'], r['sample_id']) for r in rows}) == 1270
    return a, rows


def request(judge, item):
    try:
        return ORIGINAL_REQUEST(judge, item)
    except ValueError as exc:
        if 'exceeds' not in str(exc) or (judge, item['sample_id']) not in APPROVED:
            raise
        # Recheck this local estimate for six already-reviewed, never-sent holds.
        # No packet, prompt, profile or wire parameter is changed.
        folder = BASE/'supplement/single_pass/scoring'/judge/item['sample_id']
        assert (folder/'input_hold.json').exists()
        _, profile, req = old.rec.core.request_for(judge, item)
        messages = req['body'].get('messages', req['body'].get('input'))
        text = ''.join('<|im_start|>'+m['role']+'\n'+m['content']+'<|im_end|>\n' for m in messages)+'<|im_start|>assistant\n'
        count = len(old.rec.dc.tokenizer().encode(text).ids)
        assert profile['input_token_cap'] < count <= 26800
        req['body']['max_completion_tokens' if judge == 'gpt_sol' else 'max_tokens'] = (
            8192 if judge == 'gpt_sol' else profile['output_token_cap'])
        assert item['sources'] and item['generation_failed'] is False
        return profile, req, count


def wait_baseline(judge):
    # GPT's original lane and its finite sweeps own their entire current queue.
    # Wait for the original supervisor to drain rather than contend for its slots.
    if judge != 'gpt_sol':
        return
    statusfile = BASE/(EPOCH+'_'+judge+'_status.json')
    while True:
        baseline = old.read(BASE/'scoring_completion_20261102.json')
        if baseline['state'] in ('audited', 'audit_failed'):
            assert baseline['lanes'][judge]['state'] == 'drained'
            return
        old.s.save(statusfile, dict(utc=old.s.now(), pid=os.getpid(), state='waiting_for_baseline', judge=judge))
        time.sleep(15)


def run(judge, workers=2):
    assert type(workers) is int and 1 <= workers <= 14
    a, plan = allowed_authorization()
    selected = [p for p in plan if p['judge'] == judge]
    APPROVED.update((judge, p['sample_id']) for p in selected if p['hold_reason'] == 'input_budget_hold')
    old.rec.dc.guard_operational()
    old.ev.authorize(BASE.parent/'release/protocol/test160_approval.json', 'agentic')
    old.ev.authorize(BASE.parent/'release/protocol/test160_approval.json', 'single_pass')
    old.rec.request = request
    STATE.mkdir(exist_ok=True)
    reg = Registry()
    completed = {}
    stopped = threading.Event()
    statusfile = BASE/(EPOCH+'_'+judge+'_status.json')

    def progress(state):
        old.s.save(statusfile, dict(utc=old.s.now(), pid=os.getpid(), state=state, judge=judge,
                     reviewed=len(selected), completed=len(completed), states=dict(Counter(completed.values())),
                     authorization_sha256=old.s.sha(AUTH), reviewed_plan_sha256=old.s.sha(PLAN),
                     max_additional_calls_per_item=2, old_records_preserved=True, scoring_payload_unchanged=True))

    def job(row, base):
        item = row['item']
        if stopped.is_set():
            return 'provider_stopped'
        root = base/'scoring'/judge/item['sample_id']
        if (root/'parsed.json').exists():
            return 'existing_valid_reused'
        receipt = STATE/judge/(item['sample_id']+'.json')
        receipt.parent.mkdir(parents=True, exist_ok=True)
        with exclusive_lock(root/(EPOCH+'.lock')):
            history = old.read(receipt) if receipt.exists() else dict(
                epoch=EPOCH, judge=judge, sample_id=item['sample_id'], attempts=[],
                original_hold_reason=row['_plan']['hold_reason'], authorization_sha256=old.s.sha(AUTH))
            assert history['epoch'] == EPOCH and history['judge'] == judge and history['sample_id'] == item['sample_id']
            assert history['authorization_sha256'] == old.s.sha(AUTH) and len(history['attempts']) <= 2
            while len(history['attempts']) < 2 and not stopped.is_set():
                if (root/'parsed.json').exists():
                    return 'existing_valid_reused'
                if any((f/'parsed.json').exists() for f in old.rec.folders(root)):
                    if old.rec.reconcile(root, judge, item) == 'valid':
                        return 'saved_valid_reconciled'
                profile, req, count = request(judge, item)
                assert req['url'].startswith(a['endpoint'].rstrip('/')+'/')
                assert req['body']['model'] in a['approved_models']
                for folder in old.rec.folders(root):
                    assert old.read(folder/'request.json')['request'] == req, 'Frozen request drift'
                ordinal = max([int(f.name.split('_')[-1]) for f in (root/'recovery').glob('attempt_*')]+[0])+1
                reservation = dict(ordinal=ordinal, reserved_utc=old.s.now(), request_sha256=digest(req['body']),
                                   input_token_estimate=count, state='reserved')
                history['attempts'].append(reservation)
                old.s.save(receipt, history)
                with old.slot(judge):
                    result = old.rec.attempt(root, judge, item, ordinal, reg)
                # attempt() invokes the original strict parser, including actual
                # provider input+output <=32768, identity and schema validation.
                reservation.update(state=result['status'], completed_utc=old.s.now(),
                                   reason=result.get('reason'), http_status=result.get('http_status'))
                old.s.save(root/'recovery'/('attempt_'+str(ordinal))/'owner_recovery_epoch.json',
                           dict(epoch=EPOCH, authorization_sha256=old.s.sha(AUTH), epoch_attempt=len(history['attempts'])))
                old.s.save(receipt, history)
                if result['status'] == 'valid':
                    return old.rec.reconcile(root, judge, item)
                if result.get('reason') in ('model_identity_mismatch', 'http_401', 'http_403', 'http_404'):
                    stopped.set()
                    return 'provider_or_identity_stop'
                time.sleep(5)
            return 'extra_epoch_exhausted' if not stopped.is_set() else 'provider_stopped'

    with exclusive_lock(BASE/(EPOCH+'_'+judge+'.lock')):
        wait_baseline(judge)
        progress('preflight')
        for mode, base in [('agentic', BASE), ('single_pass', BASE/'supplement/single_pass')]:
            packet = old.read(base/'scoring/packet.json')
            assert packet['protocol_sha256'] == old.s.sha(base/'protocol.json')
            by_id = {p['item']['sample_id']:p for p in packet['items']}
            jobs = []
            for p in selected:
                if p['mode'] != mode:
                    continue
                row = dict(by_id[p['sample_id']])
                assert row['generation_sha256'] == p['generation_sha256'] == old.s.sha(old.s.RUN/row['generation_file'])
                assert not row['item']['generation_failed']
                row['_plan'] = p
                jobs.append(row)
            old.s.OUT = base
            progress('running')
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = {pool.submit(job, row, base):row for row in jobs}
                for future in as_completed(futures):
                    sid = futures[future]['item']['sample_id']
                    try:
                        state = future.result()
                    except Exception as exc:
                        stopped.set()
                        state = 'exception_'+type(exc).__name__+':'+str(exc)[:180]
                    completed[sid] = state
                    print(json.dumps(dict(judge=judge, sample_id=sid, status=state, utc=old.s.now())), flush=True)
                    progress('running')
        progress('held' if stopped.is_set() else 'finished')


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--judge', choices=old.s.JUDGES, required=True)
    run(p.parse_args().judge)
