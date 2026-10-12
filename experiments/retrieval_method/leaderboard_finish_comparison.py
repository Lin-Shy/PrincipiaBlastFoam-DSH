"""等待候选全量运行、回放和普通评审，再续接无效评审并生成兼容总榜。"""
from __future__ import annotations
import argparse
import fcntl
import os
from pathlib import Path
import time
import leaderboard_audit as audit
import leaderboard_results as quality
from leaderboard_continue import run, wait_unlocked


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    for name in ['supervisor', 'config', 'python', 'key-file', 'output']:
        cli.add_argument('--'+name, type=Path, required=True)
    a = cli.parse_args()
    out = a.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    with (out/'runtime.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = {'pid': os.getpid(), 'completed': False}
        def mark(status):
            state['status'] = status
            audit.save(out/'state.json', state)
            print(status, flush=True)
        mark('waiting_for_candidate_run_replay_and_reviews')
        while True:
            parent = audit.read(a.supervisor/'state.json')
            if parent.get('completed'):
                break
            if not Path('/proc', str(parent['pid'])).exists():
                mark('parent_stopped_before_completion')
                return
            time.sleep(20)
        config = audit.read(a.config)
        cohort = next(c for c in config['cohorts'] if c['name'] == 'candidate')
        root, reviews = Path(cohort['run']), Path(cohort['reviews'])
        adjudications = [Path(p) for p in cohort['adjudications']]
        latest = adjudications[-1]
        wait_unlocked(latest)
        for attempt in range(3):
            mark('candidate_invalid_review_correction_'+str(attempt+1))
            run([str(a.python), str(latest/'leaderboard_adjudication.py'), 'run',
                 '--run', str(root), '--reviews', str(reviews), '--output', str(latest),
                 '--key-file', str(a.key_file), '--workers', '2'], out, 'adjudication-'+str(attempt+1))
            report = quality.assemble(root, reviews, out/'candidate-quality.json', adjudications)
            if report['all_arms_rankable']:
                break
        if not report['all_arms_rankable']:
            mark('candidate_still_has_unresolved_evidence')
            return
        mark('revalidate_and_combine_development_cohorts')
        code = run([str(a.python), str(Path(__file__).with_name('leaderboard_comparison.py')),
                    '--config', str(a.config), '--output', str(out/'comparison')], out, 'comparison')
        state['completed'] = code == 0
        state['remaining'] = 'True preregistered ablations, final method freeze, holdout and complete cost report.'
        mark('development_comparison_complete' if code == 0 else 'comparison_validation_failed')


if __name__ == '__main__':
    main()
