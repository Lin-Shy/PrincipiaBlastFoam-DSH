"""Owner-authorized recovery after provider restoration. Never resend uncertain POSTs."""
import argparse,json,time,os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
from contextlib import contextmanager
import single_pass_dev40 as s
import test160_evaluation as ev
import dev40_finalize as rec
import test160_closure_audit as audit
from central_execution import Registry,exclusive_lock

BASE=s.RUN/'test160_runs'
def read(p):return s.load(p)
@contextmanager
def slot(judge):
    root=BASE/'service_slots';root.mkdir(exist_ok=True)
    while True:
        acquired=None
        for i in range(2):
            p=root/(judge+'_'+str(i)+'.lock')
            try:
                with p.open('x',encoding='utf-8') as f:json.dump(dict(pid=os.getpid(),utc=s.now()),f)
                acquired=p;break
            except FileExistsError:pass
        if acquired:break
        time.sleep(1)
    try:yield
    finally:acquired.unlink()

def eligible(root,judge,item,retry_rejected_model=False):
    if item['generation_failed'] or (root/'parsed.json').exists():return False,'reuse_or_failure'
    if (root/'input_hold.json').exists():return False,'input_hold'
    folders=rec.folders(root)
    if len(list((root/'recovery').glob('attempt_*')))>=3:return False,'attempt_limit'
    _,req,_=rec.request(judge,item)
    for f in folders:
        if read(f/'request.json')['request']!=req:raise ValueError('Frozen request drift')
        state=read(f/'status.json') if (f/'status.json').exists() else {}
        if not (f/'response.txt').exists():return False,'uncertain_no_response'
        raw=read(f/'response.txt')
        # Complete explicit provider rejection is known not to contain a grade.
        explicit_error=isinstance(raw,dict) and isinstance(raw.get('error'),dict) and not raw.get('choices') and not raw.get('output')
        if state.get('http_status')==403 and explicit_error:continue
        if state.get('http_status') in rec.RETRY_HTTP:continue
        if retry_rejected_model and state.get('http_status')==404 and explicit_error and raw['error'].get('code')=='model_not_found':continue
        if explicit_error and raw['error'].get('type')=='upstream_error':continue
        if state.get('reason') in ['Duplicate/mismatched criteria','Truncated/multiple response','Unexpected or missing contract fields','Provider exceeds 32K combined context']:continue
        return False,'identity_or_uncertain_hold'
    return True,'explicit_rejection_or_unsent'

def run(auth,judge,probe=False,retry_rejected_model=False):
    rec.dc.guard_operational();reg=Registry();jobs=[];held={}
    for mode,base in [('agentic',BASE),('single_pass',BASE/'supplement/single_pass')]:
        ev.authorize(auth,mode)
        packet=read(base/'scoring/packet.json');assert packet['protocol_sha256']==s.sha(base/'protocol.json')
        for row in packet['items']:
            assert s.sha(s.RUN/row['generation_file'])==row['generation_sha256']
            root=base/'scoring'/judge/row['item']['sample_id']
            ok,reason=eligible(root,judge,row['item'],retry_rejected_model)
            if ok:jobs.append((base,root,row['item']))
            else:held[reason]=held.get(reason,0)+1
            if probe and jobs:break
        if probe and jobs:break
    print(json.dumps(dict(judge=judge,eligible=len(jobs),held=held)),flush=True)
    s.save(BASE/('resume_'+judge+'_preflight.json'),dict(utc=s.now(),eligible=len(jobs),held=held,owner_service_restoration_confirmed=True,prior_stop_preserved=True,no_uncertain_resend=True))
    if probe:jobs=jobs[:1]
    stop=__import__('threading').Event()
    completed={}
    statusfile=BASE/('resume_'+judge+'_status.json')
    def progress(state):
        s.save(statusfile,dict(utc=s.now(),pid=os.getpid(),judge=judge,state=state,probe=probe,
          planned=len(jobs),completed=len(completed),states=dict(__import__('collections').Counter(completed.values())),
          held_preflight=held,prior_stop_preserved=True,manifest_sha256=s.sha(ev.runner.MANIFEST)))
    progress('running')
    def job(args):
        base,root,item=args
        if stop.is_set():return 'provider_stopped'
        # attempt uses s.OUT for ledger/protocol; original request body is unchanged.
        # modes are run serially below to avoid the global output binding racing.
        for _ in range(3):
            ok,reason=eligible(root,judge,item,retry_rejected_model)
            if not ok:return reason
            if stop.is_set():return 'provider_stopped'
            ordinal=len(list((root/'recovery').glob('attempt_*')))+1
            with slot(judge):result=rec.attempt(root,judge,item,ordinal,reg)
            if result['status']=='valid':return rec.reconcile(root,judge,item)
            if result.get('reason') in ['model_identity_mismatch','usage_unknown_stop_and_reconcile','http_403','http_404']:
                stop.set();return 'provider_or_identity_stop'
            if result.get('http_status') not in rec.RETRY_HTTP:return 'held_after_attempt'
            time.sleep(5 if ordinal<2 else 20)
        return 'attempt_limit'
    with exclusive_lock(BASE/('resume_'+judge+'.lock')):
        for base in [BASE,BASE/'supplement/single_pass']:
            s.OUT=base
            with ThreadPoolExecutor(max_workers=2) as pool:
                fs={pool.submit(job,x):x for x in jobs if x[0]==base}
                for f in as_completed(fs):
                    if f.cancelled():continue
                    _,root,item=fs[f]
                    try:status=f.result()
                    except Exception as exc:stop.set();status='exception_'+type(exc).__name__+':'+str(exc)[:200]
                    print(json.dumps(dict(judge=judge,sample_id=item['sample_id'],status=status,utc=s.now())),flush=True)
                    completed[item['sample_id']]=status;progress('running')
                    if stop.is_set():
                        for future in fs:future.cancel()
            if stop.is_set():break
    progress('held' if stop.is_set() else 'finished')
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--authorization',type=Path,required=True);p.add_argument('--judge',choices=s.JUDGES,required=True);p.add_argument('--probe',action='store_true');p.add_argument('--retry-rejected-model',action='store_true',help='After owner-confirmed service restoration only; retry a complete model_not_found rejection within the existing attempt limit');a=p.parse_args();run(a.authorization,a.judge,a.probe,a.retry_rejected_model)
