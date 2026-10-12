"""等待当前批次后续跑冻结请求、来源审阅和回放；无效评审不会被自动改分。"""
from __future__ import annotations
import argparse
import fcntl
import os
from pathlib import Path
import subprocess
import time
import leaderboard_audit as audit
import leaderboard_results as results
import leaderboard_admission as admission


def wait_unlocked(root):
    while True:
        with (root/'runtime.lock').open('a+') as lock:
            try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:pass
            else:return
        time.sleep(20)


def run(command,output,label):
    path=output/(label+'.log')
    with path.open('a') as log:
        return subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,env={**os.environ,'PYTHONHASHSEED':'0'}).returncode


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    for name in ['python','run','reviews','key-file','output']:
        cli.add_argument('--'+name,type=Path,required=True)
    cli.add_argument('--adjudications',type=Path,action='append',required=True)
    a=cli.parse_args();root=a.run.resolve();reviews=a.reviews.resolve();out=a.output.resolve()
    adjudications=[p.resolve() for p in a.adjudications];out.mkdir(parents=True,exist_ok=True)
    with (out/'supervisor.lock').open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        state={'pid':os.getpid(),'status':'waiting_for_existing_baseline','completed':False}
        def mark(stage):state['status']=stage;audit.save(out/'state.json',state);print(stage,flush=True)
        def stop_on_failure(code, stage):
            if code == 0:return False
            state['last_exit_code']=code
            mark(stage+'_waiting_for_network_resume' if code==75 else stage+'_failed')
            return True
        def run_with_network_resume(command, label, stage):
            resume = 0
            while True:
                code = run(command, out, label)
                if code != 75:
                    return code
                resume += 1
                state['last_exit_code'] = code
                state['network_resumes'] = state.get('network_resumes', 0) + 1
                mark(stage+'_waiting_for_network_resume')
                time.sleep(10)
                mark(stage+'_network_resume_'+str(resume))
        mark('waiting_for_existing_baseline');wait_unlocked(root)
        # Three is an upper bound; frozen fetch refuses attempts beyond its existing nine-attempt cap.
        for i in range(3):
            mark('baseline_resume_'+str(i+1))
            audit.verify(root)
            code=run_with_network_resume([str(a.python),str(root/'runner.py'),'run','--run',str(root),'--key-file',str(a.key_file),'--workers','4'],'baseline-resume-'+str(i+1),'baseline')
            if stop_on_failure(code,'baseline'):return
            questions=audit.read(root/'control/questions.json');protocol=audit.read(root/'protocol.json')
            folders=[root/g/'sessions'/f"{q['id']}--{m}--r{rep}" for g,methods in protocol['groups'].items() for m in methods for q in questions for rep in range(1,protocol['replicates']+1)]
            if all((f/'result.json').exists() or results.terminal_failure(f) for f in folders):break
        wait_unlocked(reviews)
        for i in range(3):
            mark('source_review_resume_'+str(i+1))
            code=run_with_network_resume([str(a.python),str(reviews/'leaderboard_review.py'),'run','--run',str(root),'--output',str(reviews),'--key-file',str(a.key_file),'--workers','2'],'review-resume-'+str(i+1),'source_review')
            if stop_on_failure(code,'source_review'):return
        latest=adjudications[-1];wait_unlocked(latest)
        for i in range(3):
            mark('source_adjudication_resume_'+str(i+1))
            code=run_with_network_resume([str(a.python),str(latest/'leaderboard_adjudication.py'),'run','--run',str(root),'--reviews',str(reviews),'--output',str(latest),'--key-file',str(a.key_file),'--workers','2'],'adjudication-resume-'+str(i+1),'source_adjudication')
            if stop_on_failure(code,'source_adjudication'):return
        mark('zero_model_replay_admission')
        if not admission.check(root)['passed']:
            wait_unlocked(root)
            run([str(a.python),str(root/'runner.py'),'replay','--run',str(root),'--workers','4'],out,'zero-model-replay')
        mark('validate_and_report')
        report=results.assemble(root,reviews,out/'quality.json',adjudications)
        audit.audit(root,out/'cost-and-grid.json')
        state.update(completed=True,all_arms_rankable=report['all_arms_rankable'],
                     remaining='Candidate evaluation, ablations and frozen holdout remain; unresolved source reviews are never coerced into scores.')
        mark('baseline_followup_finished' if report['all_arms_rankable'] else 'baseline_has_unresolved_items')


if __name__=='__main__':main()
