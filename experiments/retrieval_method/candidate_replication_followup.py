"""运行与消融同期的候选故障校准复现，并完成回放和来源评审。"""
from __future__ import annotations
import argparse
import fcntl
import os
from pathlib import Path

import leaderboard_admission as admission
import leaderboard_audit as audit
import leaderboard_results as quality
from ablation_followup import call, terminal_grid
from leaderboard_continue import wait_unlocked


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    for name in ['run','python','review-python','key-file','baseline-report','reviews','adjudications','output']:
        cli.add_argument('--'+name,type=Path,required=True)
    a=cli.parse_args();root=a.run.resolve();out=a.output.resolve();reviews=a.reviews.resolve()
    adjudications=a.adjudications.resolve();out.mkdir(parents=True,exist_ok=True)
    with (out/'runtime.lock').open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        state={'pid':os.getpid(),'completed':False}
        def mark(status):state['status']=status;audit.save(out/'state.json',state);print(status,flush=True)
        protocol=audit.verify(root)
        for attempt in range(1,4):
            mark('replication_run_'+str(attempt));wait_unlocked(root)
            call([str(a.python),str(root/'candidate_runner.py'),'run','--run',str(root),
                  '--baseline-report',str(a.baseline_report),'--key-file',str(a.key_file),'--workers','2'],out,'run-'+str(attempt))
            state['terminal_sessions']=terminal_grid(root,protocol)
            if state['terminal_sessions']==protocol['planned_sessions']:break
        mark('replication_zero_model_replay');wait_unlocked(root)
        call([str(a.python),str(root/'candidate_runner.py'),'replay','--run',str(root),'--workers','2'],out,'replay-parallel')
        check=admission.check(root)
        if not check['passed']:
            mark('replication_serial_replay_repair');wait_unlocked(root)
            call([str(a.python),str(root/'candidate_runner.py'),'replay','--run',str(root),'--workers','1'],out,'replay-serial')
            check=admission.check(root)
        audit.save(out/'admission.json',check)
        if not check['passed']:
            state['admission_errors']=len(check['errors']);mark('replication_replay_unresolved');return
        wait_unlocked(reviews)
        for attempt in range(1,4):
            mark('replication_source_review_'+str(attempt))
            call([str(a.review_python),str(reviews/'leaderboard_review.py'),'run','--run',str(root),
                  '--output',str(reviews),'--key-file',str(a.key_file),'--workers','2'],out,'review-'+str(attempt))
        if not (adjudications/'protocol.json').exists():
            mark('freeze_replication_invalid_review_correction')
            call([str(a.review_python),str(Path(__file__).with_name('leaderboard_adjudication.py')),'prepare',
                  '--run',str(root),'--reviews',str(reviews),'--output',str(adjudications)],out,'adjudication-prepare')
        wait_unlocked(adjudications)
        for attempt in range(1,4):
            mark('replication_invalid_review_correction_'+str(attempt))
            call([str(a.review_python),str(adjudications/'leaderboard_adjudication.py'),'run',
                  '--run',str(root),'--reviews',str(reviews),'--output',str(adjudications),
                  '--key-file',str(a.key_file),'--workers','2'],out,'adjudication-'+str(attempt))
            report=quality.assemble(root,reviews,out/'quality.json',[adjudications])
            if report['all_arms_rankable']:break
        state['completed']=report['all_arms_rankable'];state['all_arms_rankable']=report['all_arms_rankable']
        state['remaining']='Use this cohort as contemporaneous ablation reference; retain candidate_v5 separately.'
        mark('replication_complete' if state['completed'] else 'replication_source_reviews_unresolved')


if __name__=='__main__':main()
