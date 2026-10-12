"""续跑预注册消融、回放、来源评审和机械无效评审纠正。"""
from __future__ import annotations
import argparse
import fcntl
import os
from pathlib import Path
import subprocess

import leaderboard_admission as admission
import leaderboard_audit as audit
import leaderboard_results as quality
from leaderboard_continue import wait_unlocked


def call(command, output, label):
    path = output/(label+'.log')
    with path.open('a') as log:
        return subprocess.run(command, stdout=log, stderr=subprocess.STDOUT,
                              env={**os.environ, 'PYTHONHASHSEED': '0'}).returncode


def terminal_grid(root, protocol):
    questions = audit.read(root/'control/questions.json')
    complete = 0
    for arm, methods in protocol['groups'].items():
        for method in methods:
            for question in questions:
                for replicate in range(1, protocol['replicates']+1):
                    folder = root/arm/'sessions'/f"{question['id']}--{method}--r{replicate}"
                    if (folder/'result.json').exists() or quality.terminal_failure(folder):
                        complete += 1
    return complete


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    for name in ['run', 'python', 'review-python', 'key-file', 'reviews', 'adjudications', 'output']:
        cli.add_argument('--'+name, type=Path, required=True)
    a = cli.parse_args(); root = a.run.resolve(); out = a.output.resolve()
    reviews = a.reviews.resolve(); adjudications = a.adjudications.resolve(); out.mkdir(parents=True, exist_ok=True)
    with (out/'runtime.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = {'pid': os.getpid(), 'completed': False}
        def mark(status):
            state['status'] = status; audit.save(out/'state.json', state); print(status, flush=True)
        protocol = audit.verify(root)
        for attempt in range(1, 4):
            mark('ablation_run_'+str(attempt))
            wait_unlocked(root)
            code = call([str(a.python), str(root/'candidate_ablation.py'), 'run', '--run', str(root),
                         '--key-file', str(a.key_file), '--workers', '4'], out, 'run-'+str(attempt))
            if code:
                state['last_exit_code'] = code
                mark('ablation_waiting_for_network_resume' if code == 75 else 'ablation_runner_failed')
                return
            state['terminal_sessions'] = terminal_grid(root, protocol)
            if state['terminal_sessions'] == protocol['planned_sessions']:
                break
        mark('ablation_zero_model_replay_parallel')
        wait_unlocked(root)
        call([str(a.python), str(root/'candidate_ablation.py'), 'replay', '--run', str(root), '--workers', '4'],
             out, 'replay-parallel')
        check = admission.check(root)
        if not check['passed']:
            mark('ablation_zero_model_replay_serial_repair')
            wait_unlocked(root)
            call([str(a.python), str(root/'candidate_ablation.py'), 'replay', '--run', str(root), '--workers', '1'],
                 out, 'replay-serial')
            check = admission.check(root)
        audit.save(out/'admission.json', check)
        if not check['passed']:
            state['admission_errors'] = len(check['errors']); mark('ablation_replay_unresolved'); return
        wait_unlocked(reviews)
        for attempt in range(1, 4):
            mark('ablation_source_review_'+str(attempt))
            code = call([str(a.review_python), str(reviews/'leaderboard_review.py'), 'run', '--run', str(root),
                         '--output', str(reviews), '--key-file', str(a.key_file), '--workers', '2'],
                        out, 'review-'+str(attempt))
            if code:
                state['last_exit_code'] = code
                mark('ablation_review_waiting_for_network_resume' if code == 75 else 'ablation_review_failed')
                return
        if not (adjudications/'protocol.json').exists():
            mark('freeze_invalid_review_correction')
            call([str(a.review_python), str(Path(__file__).with_name('leaderboard_adjudication.py')), 'prepare',
                  '--run', str(root), '--reviews', str(reviews), '--output', str(adjudications)],
                 out, 'adjudication-prepare')
        wait_unlocked(adjudications)
        for attempt in range(1, 4):
            mark('invalid_review_correction_'+str(attempt))
            code = call([str(a.review_python), str(adjudications/'leaderboard_adjudication.py'), 'run',
                         '--run', str(root), '--reviews', str(reviews), '--output', str(adjudications),
                         '--key-file', str(a.key_file), '--workers', '2'], out, 'adjudication-'+str(attempt))
            if code:
                state['last_exit_code'] = code
                mark('ablation_adjudication_waiting_for_network_resume' if code == 75 else 'ablation_adjudication_failed')
                return
            report = quality.assemble(root, reviews, out/'quality.json', [adjudications])
            if report['all_arms_rankable']:
                break
        state['completed'] = report['all_arms_rankable']
        state['all_arms_rankable'] = report['all_arms_rankable']
        state['remaining'] = 'Analyze all registered effects, freeze final method, then open and evaluate holdout.'
        mark('ablation_evaluation_complete' if state['completed'] else 'ablation_source_reviews_unresolved')


if __name__ == '__main__':
    main()
