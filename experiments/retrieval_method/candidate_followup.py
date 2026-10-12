"""基线通过全量来源审阅和回放后，续跑已冻结候选与强无图的完整开发评测。"""
from __future__ import annotations
import argparse
import fcntl
import json
import os
from pathlib import Path
import time
import leaderboard_audit as audit
import leaderboard_results as quality
from leaderboard_continue import run,wait_unlocked


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    for name in ['baseline','baseline-reviews','baseline-followup','candidate','python','review-python','key-file','output']:
        cli.add_argument('--'+name,type=Path,required=True)
    cli.add_argument('--adjudications',type=Path,action='append',required=True)
    a=cli.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=True)
    baseline=a.baseline.resolve();candidate=a.candidate.resolve();reviews=a.baseline_reviews.resolve()
    with (out/'runtime.lock').open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        state={'pid':os.getpid(),'status':'waiting_for_baseline_followup','completed':False}
        def mark(stage):state['status']=stage;audit.save(out/'state.json',state);print(stage,flush=True)
        mark('waiting_for_baseline_followup')
        while True:
            try:parent=audit.read(a.baseline_followup/'state.json')
            except (FileNotFoundError,json.JSONDecodeError):time.sleep(20);continue
            if parent.get('completed'):break
            if not Path('/proc',str(parent['pid'])).exists():
                mark('baseline_supervisor_stopped_before_completion');return
            time.sleep(20)
        mark('revalidate_baseline_source_reviews_and_replay')
        report=quality.assemble(baseline,reviews,out/'baseline-admission-quality.json',[p.resolve() for p in a.adjudications])
        if not report['all_arms_rankable']:
            mark('baseline_source_review_or_replay_unresolved');return
        protocol=audit.verify(candidate)
        if protocol['parent_protocol_sha256']!=report['protocol_sha256']:raise ValueError('candidate baseline gate drift')
        state['baseline_quality_sha256']=audit.sha(out/'baseline-admission-quality.json')
        wait_unlocked(candidate)
        for i in range(3):
            mark('candidate_full_development_run_'+str(i+1))
            run([str(a.python),str(candidate/'candidate_runner.py'),'run','--run',str(candidate),
                 '--baseline-report',str(out/'baseline-admission-quality.json'),'--key-file',str(a.key_file),'--workers','4'],out,'candidate-run-'+str(i+1))
            if len(list(candidate.glob('*/sessions/*/result.json')))==protocol['planned_sessions']:break
        mark('candidate_zero_model_replay')
        run([str(a.python),str(candidate/'candidate_runner.py'),'replay','--run',str(candidate),'--workers','4'],out,'candidate-replay')
        target=candidate.parent.parent/'reviews/candidate_v1'
        source=Path(__file__).with_name('leaderboard_review.py')
        if not (target/'protocol.json').exists():
            run([str(a.review_python),str(source),'prepare','--run',str(candidate),'--output',str(target)],out,'candidate-review-prepare')
        wait_unlocked(target)
        for i in range(3):
            mark('candidate_source_review_'+str(i+1))
            run([str(a.review_python),str(target/'leaderboard_review.py'),'run','--run',str(candidate),
                 '--output',str(target),'--key-file',str(a.key_file),'--workers','2'],out,'candidate-review-'+str(i+1))
        mark('candidate_quality_report')
        result=quality.assemble(candidate,target,out/'candidate-quality.json')
        state.update(completed=True,all_arms_rankable=result['all_arms_rankable'],
            remaining='Resolve any invalid source reviews, then execute the preregistered true ablations. Final method freeze and holdout remain pending.')
        mark('candidate_development_finished' if result['all_arms_rankable'] else 'candidate_source_reviews_unresolved')


if __name__=='__main__':main()
