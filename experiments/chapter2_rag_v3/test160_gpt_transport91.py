"""Owner-authorized 91-item GPT transport recovery, capped at 182 calls."""
import csv
import os
import time
import test160_extra_recovery as engine

BASE = engine.BASE
EPOCH = 'gpt_transport91_20261102'
AUTH = BASE/'gpt_transport91_authorization_20261102.json'
PLAN = BASE/'gpt_transport91_plan_20261102.csv'
REVIEW = BASE/'gpt_new_transport_review_20261102_1532.json'


def authorization():
    a = engine.old.read(AUTH)
    assert a['owner_confirmed'] and a['epoch'] == EPOCH
    assert a['manifest_sha256'] == engine.old.s.sha(engine.old.ev.runner.MANIFEST)
    assert a['max_physical_requests'] == 182
    assert a['max_additional_calls_per_judging_task'] == 2
    assert a['unresolved_prior_requests_may_be_reissued']
    assert a['reviewed_plan_sha256'] == engine.old.s.sha(PLAN)
    assert a['review_sha256'] == engine.old.s.sha(REVIEW)
    review = engine.old.read(REVIEW)
    proposal = BASE/review['proposal_csv']
    assert a['proposal_sha256'] == review['proposal_sha256'] == engine.old.s.sha(proposal)
    rows = list(csv.DictReader(PLAN.open(encoding='utf-8-sig')))
    original = list(csv.DictReader(proposal.open(encoding='utf-8-sig')))
    assert len(rows) == a['reviewed_judging_tasks'] == 91
    assert len({r['sample_id'] for r in rows}) == 91
    assert all(r['judge'] == 'gpt_sol' and r['hold_reason'] == 'transport_unknown_no_resend'
               and r['error_type'] in ('RemoteDisconnected', 'SSLEOFError') for r in rows)
    assert [{k: v for k, v in r.items() if k != 'hold_reason'} for r in rows] == original
    prior = list(csv.DictReader((BASE/'remaining_recovery_review_20261102.csv').open(encoding='utf-8-sig')))
    assert not ({r['sample_id'] for r in rows} & {r['sample_id'] for r in prior if r['judge'] == 'gpt_sol'})
    return a, rows


def wait_predecessors(judge):
    assert judge == 'gpt_sol'
    while True:
        baseline = engine.old.read(BASE/'scoring_completion_20261102.json')
        prior = engine.old.read(BASE/'extra_recovery_20261102_gpt_sol_status.json')
        if baseline['state'] in ('audited', 'audit_failed') and prior['state'] == 'finished':
            assert baseline['lanes'][judge]['state'] == 'drained'
            return
        engine.old.s.save(BASE/(EPOCH+'_'+judge+'_status.json'), dict(
            utc=engine.old.s.now(), pid=os.getpid(), state='waiting_for_predecessors', judge=judge,
            reviewed=91, max_physical_requests=182, authorization_sha256=engine.old.s.sha(AUTH)))
        time.sleep(15)


def main():
    authorization()
    engine.EPOCH = EPOCH
    engine.AUTH = AUTH
    engine.PLAN = PLAN
    engine.STATE = BASE/EPOCH
    engine.allowed_authorization = authorization
    engine.wait_baseline = wait_predecessors
    engine.run('gpt_sol')


if __name__ == '__main__':
    main()
