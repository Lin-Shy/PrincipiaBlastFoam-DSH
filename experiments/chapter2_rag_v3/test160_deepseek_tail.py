"""Seven-item follow-up authorized by the owner after the first epoch drained.

Reuses the bounded epoch engine without changing its historical authorization,
receipts, scores or wire payload. Separate receipts cap this epoch at 14 calls.
"""
import csv
import test160_extra_recovery as engine

BASE = engine.BASE
EPOCH = 'deepseek_tail_20261102'
AUTH = BASE/'deepseek_tail_authorization_20261102.json'
PLAN = BASE/'deepseek_tail_plan_20261102.csv'
REVIEW = BASE/'deepseek_exhausted_review_20261102.json'


def authorization():
    a=engine.old.read(AUTH)
    assert a['owner_confirmed'] and a['epoch']==EPOCH
    assert a['manifest_sha256']==engine.old.s.sha(engine.old.ev.runner.MANIFEST)
    assert a['max_physical_requests']==14 and a['max_additional_calls_per_judging_task']==2
    assert a['unresolved_prior_requests_may_be_reissued']
    assert a['reviewed_plan_sha256']==engine.old.s.sha(PLAN)
    assert a['review_sha256']==engine.old.s.sha(REVIEW)
    rows=list(csv.DictReader(PLAN.open(encoding='utf-8-sig')))
    reviewed=engine.old.read(REVIEW)['items']
    assert len(rows)==a['reviewed_judging_tasks']==7
    assert len({r['sample_id'] for r in rows})==7
    assert all(r['judge']=='deepseek_flash' and r['hold_reason']=='extra_epoch_exhausted' for r in rows)
    assert {r['sample_id']:r['generation_sha256'] for r in rows}=={r['sample_id']:r['generation_sha256'] for r in reviewed}
    prior=engine.old.read(BASE/'extra_recovery_20261102_deepseek_flash_status.json')
    assert prior['state']=='finished' and prior['completed']==prior['reviewed']==978
    return a,rows


def main():
    authorization()
    # This is process-local configuration of the same finite engine. GPT and
    # the original epoch retain their own immutable configuration and receipts.
    engine.EPOCH=EPOCH
    engine.AUTH=AUTH
    engine.PLAN=PLAN
    engine.STATE=BASE/EPOCH
    engine.allowed_authorization=authorization
    engine.run('deepseek_flash')


if __name__=='__main__':
    main()
