"""Refresh the in-progress report; audit once all 4472 tasks terminate.

This process never sends model requests and never retries or deletes records.
"""
import json
import subprocess
import sys
import time
from pathlib import Path
import objective_json_full as full

HERE = Path(__file__).resolve().parent
STATE = full.OUT / 'monitor.json'


def write(status, **extra):
    tmp = STATE.with_suffix('.tmp')
    tmp.write_text(json.dumps(dict(status=status, **extra), ensure_ascii=False, indent=2) + '\n', encoding='utf8')
    tmp.replace(STATE)


def run(script):
    return subprocess.run([sys.executable, str(HERE / script)], capture_output=True, text=True, encoding='utf8', errors='replace')


def main():
    previous = -1
    unchanged = 0
    while True:
        result = run('objective_json_report.py')
        if result.returncode:
            write('report_error', error=result.stderr[-3000:]); return 1
        snapshot = json.loads((full.OUT / 'results/snapshot.json').read_text(encoding='utf8'))
        completed = snapshot['completed']
        if snapshot['status'] == 'closed':
            audit = run('objective_json_audit.py')
            if audit.returncode:
                write('audit_error', completed=completed, error=audit.stderr[-3000:]); return 1
            write('audited', completed=completed, note='Thesis synchronization, PDF review, and cleanup still require completion.')
            return 0
        unchanged = unchanged + 1 if completed == previous else 0
        write('running' if unchanged < 20 else 'stalled', completed=completed, planned=snapshot['planned'])
        if unchanged >= 20:
            return 2
        previous = completed
        time.sleep(45)


if __name__ == '__main__':
    raise SystemExit(main())
