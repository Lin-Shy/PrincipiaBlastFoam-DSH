"""Schedule disjoint authorized GPT recovery alongside the original two workers.

Only scheduling changes: existing epoch authorizations and receipts still bound
every physical request. The original queue remains untouched.
"""
import argparse
from contextlib import contextmanager
import json
import os
import time
import test160_extra_recovery as engine
import test160_gpt_transport91 as tail

BASE = engine.BASE
CONTROL = BASE/'gpt_concurrency_control_20261102.json'


def capacity():
    value = engine.old.read(CONTROL)['gpt_total_slot_cap']
    assert type(value) is int and value in (2, 4)
    return value


@contextmanager
def slot(judge):
    assert judge == 'gpt_sol'
    root = BASE/'service_slots'
    root.mkdir(exist_ok=True)
    acquired = None
    while acquired is None:
        limit = capacity()
        for i in ([2, 3, 0, 1] if limit == 4 else [0, 1]):
            path = root/(judge+'_'+str(i)+'.lock')
            try:
                with path.open('x', encoding='utf-8') as f:
                    json.dump(dict(pid=os.getpid(), utc=engine.old.s.now()), f)
                acquired = path
                break
            except FileExistsError:
                pass
        if acquired is None:
            time.sleep(1)
    try:
        yield
    finally:
        acquired.unlink()


def partition_disjoint(judge, selected):
    """Original queued jobs must exclude every proposed auxiliary request."""
    assert judge == 'gpt_sol'
    packets = {}
    for mode, base in [('agentic', BASE), ('single_pass', BASE/'supplement/single_pass')]:
        packets[mode] = (base, {r['item']['sample_id']: r for r in
                               engine.old.read(base/'scoring/packet.json')['items']})
    safe, deferred = [], []
    for p in selected:
        base, rows = packets[p['mode']]
        row = rows[p['sample_id']]
        assert row['generation_sha256'] == p['generation_sha256']
        root = base/'scoring'/judge/p['sample_id']
        folders = engine.old.rec.folders(root)
        excluded = ((root/'parsed.json').exists() or (root/'input_hold.json').exists()
                    or len(list((root/'recovery').glob('attempt_*'))) >= 3)
        for folder in folders:
            if (folder/'response.txt').exists():
                continue
            state = engine.old.read(folder/'status.json') if (folder/'status.json').exists() else {}
            dns_before_post = (state.get('error_type') == 'gaierror'
                and state.get('http_status') is None and state.get('completed_utc')
                and 'getaddrinfo failed' in state.get('reason', ''))
            if not dns_before_post:
                excluded = True
        # These are the original worker's unconditional exclusion conditions;
        # only the remaining exceptional cases need its expensive tokenizer.
        eligible = False if excluded else engine.old.eligible(root, judge, row['item'])[0]
        (deferred if eligible else safe).append(p)
    return safe, deferred


def wait_tail(judge):
    while True:
        prior = engine.old.read(BASE/'extra_recovery_20261102_gpt_sol_status.json')
        if prior['state'] in ('finished', 'waiting_for_baseline_deferred'):
            return
        engine.old.s.save(BASE/(tail.EPOCH+'_'+judge+'_status.json'), dict(
            utc=engine.old.s.now(), pid=os.getpid(), state='waiting_for_extra_epoch',
            judge=judge, reviewed=91, max_physical_requests=182,
            authorization_sha256=engine.old.s.sha(tail.AUTH)))
        time.sleep(15)


def main(lane):
    capacity()
    deferred = []
    original_authorization = engine.allowed_authorization
    if lane == 'extra':
        _, rows = original_authorization()
        selected = [r for r in rows if r['judge'] == 'gpt_sol']
        assert len(selected) == 292
        safe, deferred = partition_disjoint('gpt_sol', selected)
        safe_ids = {p['sample_id'] for p in safe}
        # A subset consumes the same sealed epoch receipts and budget. Items
        # still eligible in the original queue wait for its terminal audit.
        def subset_authorization():
            a, all_rows = original_authorization()
            return a, [p for p in all_rows if p['judge'] != 'gpt_sol' or p['sample_id'] in safe_ids]
        engine.allowed_authorization = subset_authorization
        engine.wait_baseline = lambda judge: None
    else:
        _, rows = tail.authorization()
        _, conflicts = partition_disjoint('gpt_sol', rows)
        assert not conflicts, 'Tail item overlaps original queue'
        engine.EPOCH, engine.AUTH, engine.PLAN = tail.EPOCH, tail.AUTH, tail.PLAN
        engine.STATE = BASE/tail.EPOCH
        engine.allowed_authorization = tail.authorization
        engine.wait_baseline = wait_tail
    engine.old.slot = slot
    engine.old.s.save(BASE/('gpt_acceleration_'+lane+'_preflight.json'), dict(
        utc=engine.old.s.now(), pid=os.getpid(), total_slot_cap=capacity(),
        deferred_original_queue=[p['sample_id'] for p in deferred],
        unchanged_epoch_authorization=True, no_new_budget=True))
    engine.run('gpt_sol')
    if deferred:
        statusfile = BASE/'extra_recovery_20261102_gpt_sol_status.json'
        if engine.old.read(statusfile)['state'] != 'finished':
            return
        engine.old.s.save(BASE/'gpt_acceleration_extra_parallel_finished.json',
                          engine.old.read(statusfile))
        while True:
            baseline = engine.old.read(BASE/'scoring_completion_20261102.json')
            if baseline['state'] in ('audited', 'audit_failed'):
                assert baseline['lanes']['gpt_sol']['state'] == 'drained'
                break
            engine.old.s.save(statusfile, dict(utc=engine.old.s.now(), pid=os.getpid(),
                state='waiting_for_baseline_deferred', judge='gpt_sol',
                deferred_original_queue=[p['sample_id'] for p in deferred],
                completed_parallel_status='gpt_acceleration_extra_parallel_finished.json'))
            time.sleep(15)
        engine.allowed_authorization = original_authorization
        engine.run('gpt_sol')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--lane', choices=['extra', 'transport91'], required=True)
    main(parser.parse_args().lane)
