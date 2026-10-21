"""Frozen e2e worker with a between-session stop on infrastructure failures.

Requests, tools, model, ranking and answers remain the frozen implementation.
Every result is saved before checking whether another session can start.
"""
import argparse
from common import *

class InfrastructureStop(RuntimeError):
    pass

def stopping_reason(result, consecutive_transport):
    status=result.get('status')
    turns=result.get('turns',[])
    response=turns[-1].get('response',{}) if turns else {}
    if response.get('http_status') in {401,402,403,429}:
        return 'provider_auth_quota_or_rate_rejection'
    if status in {'model_mismatch','model_identity_mismatch','provider_output_budget_violation'}:
        return 'provider_identity_or_budget_violation'
    if consecutive_transport>=3:
        return 'three_consecutive_transport_failures'
    return None

def main(arm,run_id,approval):
    import e2e
    original=e2e.save
    transport_streak=0
    def recorded_save(path,value):
        nonlocal transport_streak
        original(path,value)
        if Path(path).name!='result.json':return
        transport_streak=transport_streak+1 if value.get('status') in {'transport_error','http_rejected','invalid_response'} else 0
        reason=stopping_reason(value,transport_streak)
        if reason:
            original(ARCHIVE/'e2e_runs'/run_id/arm/'infrastructure_stop.json',dict(
                reason=reason,session_id=value.get('id'),session_status=value.get('status'),
                last_result_sha256=sha(path),requests_retried=False,result_retained=True))
            raise InfrastructureStop(reason)
    e2e.save=recorded_save
    e2e.answer(arm,run_id,approval)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--arm',required=True);p.add_argument('--run-id',required=True);p.add_argument('--approval',type=Path,required=True)
    a=p.parse_args()
    try:main(a.arm,a.run_id,a.approval)
    except InfrastructureStop as error:
        print('Batch stopped between sessions:',str(error),flush=True)
        raise SystemExit(2)
