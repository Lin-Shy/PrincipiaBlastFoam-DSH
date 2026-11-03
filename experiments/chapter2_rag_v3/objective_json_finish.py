"""Prepare an audited thesis build after the asynchronous JSON run closes.

Stops on source drift or any failed step; visual review, Git staging and deletion
of the superseded experiment remain explicit follow-up steps.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import objective_experiment as exp
import objective_json_full as full

HERE = Path(__file__).resolve().parent
MS = exp.WORK / 'graduation-thesis-materials/graduation-manuscript'
RESEARCH = exp.WORK / 'graduation-thesis-materials/graduation-research/chapters/chapter02.md'
STATE = full.OUT / 'finish.json'
TARGETS = [MS/'docs/chap02_objective_results.tex', MS/'docs/abstract.tex', MS/'docs/chap05.tex',
           MS/'docs/appendix_ch02.tex', MS/'docs/chap02_objective_review.tex',
           MS/'assets/objective_metrics.tex', MS/'assets/objective_main_accuracy.pdf', MS/'main.pdf', RESEARCH]


def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def state(status, **kwargs):
    exp.save(STATE, dict(status=status, updated=exp.now(), **kwargs))


def execute(args, cwd=None):
    p = subprocess.run(args, cwd=cwd, capture_output=True, text=True, encoding='utf8', errors='replace')
    if p.returncode:
        raise RuntimeError(f'{args[0]} returned {p.returncode}: {(p.stderr or p.stdout)[-4000:]}')
    return p.stdout


def main(node, marker):
    before = {str(p): digest(p) for p in TARGETS}
    state('waiting_for_audit', source_hashes=before)
    for _ in range(1920):  # Stop after 24 hours rather than wait forever.
        monitor = full.OUT / 'monitor.json'
        if monitor.exists():
            data = exp.read(monitor)
            if data['status'] == 'audited':
                break
            if data['status'] in ('stalled', 'report_error', 'audit_error'):
                state('blocked', reason=data); return 2
        time.sleep(45)
    else:
        state('blocked', reason='audit did not complete within 24 hours'); return 2
    changed = [str(p) for p in TARGETS if not p.is_file() or digest(p) != before[str(p)]]
    if changed:
        state('blocked', reason='manuscript source changed while experiment ran', files=changed); return 2
    try:
        state('preparing_thesis')
        execute([sys.executable, str(HERE/'objective_json_publish.py')])
        execute([sys.executable, str(HERE/'objective_json_sync.py')])
        # PDF skill requires this declaration immediately before authoring.
        execute([node, marker, '--operation-kind', 'edit', '--expected-output-count', '1', '--output-format', 'pdf'])
        execute(['latexmk', '-outdir=build', '-xelatex', 'main.tex'], cwd=MS)
        shutil.copyfile(MS/'build/main.pdf', MS/'main.pdf')
        execute([sys.executable, str(MS/'tools/release.py')], cwd=MS)
        state('needs_visual_review', pdf_sha256=digest(MS/'main.pdf'),
              note='Review rendered PDF, stage only this task, and clean obsolete format results after checking references.')
        return 0
    except Exception as e:
        state('blocked', reason=str(e)); return 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--node', required=True)
    parser.add_argument('--pdf-marker', required=True)
    args = parser.parse_args()
    raise SystemExit(main(args.node, args.pdf_marker))
