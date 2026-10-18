"""Sequential recovery of unattempted frozen grading; no model/scoring policy changes.

The backend uses the already sealed preparation, probe, scoring and closure tools.
Each failed formal attempt is drained and audited before another is admitted.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import queue
import re
import subprocess
import sys
import threading
import time

PLANNED = 17136


def supervise(backend, attempt: str, prior: str):
    """Small state machine; backend methods must fail closed on integrity errors."""
    previous_completed = None
    while True:
        backend.wait_closed(attempt)
        receipt = backend.audit(attempt, prior)
        completed = receipt['completed_scores']
        if not 0 < completed <= PLANNED:
            raise ValueError('Invalid closed score count')
        if not receipt['score_bindings_verified'] or not receipt['all_scores_before_continuation_preserved']:
            raise ValueError('Closed scoring integrity not established')
        if receipt['orphan_judge_requests'] != 0:
            raise ValueError('Orphan request: no new admission')
        if previous_completed is not None and completed <= previous_completed:
            raise ValueError('Continuation produced no new terminal scores')
        if completed == PLANNED:
            return receipt
        previous_completed = completed
        admitted = None
        for probe_index in range(3):
            number = backend.prepare_next()
            probe = backend.probe(number)
            backend.archive_probe()
            if probe['passed']:
                admitted = number
                break
            if probe['permanent_rejection']:
                raise RuntimeError('Original proxy authorization/billing rejection; external recovery required')
            if probe_index < 2:
                backend.cooldown()
        if admitted is None:
            raise RuntimeError('Three independent probes failed; no formal request admitted')
        prior, attempt = attempt, backend.score(admitted, attempt, completed)


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class WindowsProcess:
    """Hold a real process handle; PID reuse cannot turn an old wait into admission."""
    def __init__(self, pid, expected_creation):
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
        kernel.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.kernel = kernel
        self.handle = kernel.OpenProcess(0x1000 | 0x100000, False, pid)
        if not self.handle:
            raise OSError(ctypes.get_last_error(), 'Required existing controller process missing')
        times = [wintypes.FILETIME() for _ in range(4)]
        if not kernel.GetProcessTimes(self.handle, *(ctypes.byref(x) for x in times)):
            self.close()
            raise OSError(ctypes.get_last_error(), 'Cannot bind existing process creation time')
        created = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime
        if created != expected_creation:
            self.close()
            raise ValueError('Existing controller PID creation identity changed')

    def alive(self):
        code = wintypes.DWORD()
        if not self.kernel.GetExitCodeProcess(self.handle, ctypes.byref(code)):
            raise OSError(ctypes.get_last_error(), 'Cannot observe existing controller')
        return code.value == 259

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


class Backend:
    def __init__(self, registration, process):
        self.registration = registration
        self.config = read(registration)
        self.workspace = Path(self.config['workspace'])
        self.activity = self.workspace / self.config['activity']
        self.folder = self.workspace / self.config['output']
        self.process = process
        self.latest = self.config['initial_completed_scores']
        self.last_heartbeat = 0.0

    def event(self, kind, **values):
        row = dict(utc=datetime.now(timezone.utc).isoformat(), kind=kind, **values)
        with (self.folder / 'events.jsonl').open('a', encoding='utf-8') as f:
            f.write(json.dumps(row) + '\n')
        if kind != 'child_output':
            print(json.dumps(row), flush=True)

    def heartbeat(self):
        if time.monotonic() - self.last_heartbeat >= 50:
            self.last_heartbeat = time.monotonic()
            if self.process is not None:
                self.latest = max(self.latest, sum(1 for _ in (self.activity / 'formal/scores_001').rglob('score.json')))
            self.event('heartbeat', latest_completed=self.latest, planned=PLANNED)

    def check_sources(self):
        for rel, digest in self.config['driver_sha256'].items():
            if sha(self.workspace / rel) != digest:
                raise ValueError('Registered operational driver changed: ' + rel)
        if sha(self.activity / 'setup/formal_001/plan.json') != self.config['plan_sha256']:
            raise ValueError('Frozen plan changed')

    def run(self, script, arguments, callback=None):
        self.check_sources()
        relative = '.local/' + script
        if relative not in self.config['driver_sha256']:
            raise ValueError('Unregistered operational driver')
        command = [self.config['python'], '-u', str(self.workspace / relative), *map(str, arguments)]
        child = subprocess.Popen(command, cwd=self.workspace, stdout=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, text=True, encoding='utf-8',
                                 errors='backslashreplace', env=dict(os.environ, PYTHONIOENCODING='utf-8'))
        self.event('child_started', driver=script, pid=child.pid, arguments=list(map(str, arguments)))
        lines = queue.Queue()
        def consume():
            try:
                for line in child.stdout:
                    lines.put(line)
            finally:
                lines.put(None)
        reader = threading.Thread(target=consume, daemon=True)
        reader.start()
        done = False
        callback_error = None
        while not done:
            try:
                line = lines.get(timeout=2)
            except queue.Empty:
                self.heartbeat()
                continue
            if line is None:
                done = True
                continue
            self.event('child_output', driver=script, text=line.rstrip())
            match = re.search(r"'scored': (\d+)", line)
            if match:
                self.latest = max(self.latest, int(match.group(1)))
            if callback is not None and callback_error is None:
                try:
                    callback(line)
                except Exception as exc:
                    # Never abandon/kill a live formal controller after a side-audit failure.
                    callback_error = exc
                    self.event('side_audit_failed_waiting_for_child', error_type=type(exc).__name__)
            self.heartbeat()
        code = child.wait()
        reader.join()
        self.event('child_closed', driver=script, exit_code=code)
        if callback_error is not None:
            raise callback_error
        return code

    def require(self, script, arguments):
        code = self.run(script, arguments)
        if code != 0:
            raise RuntimeError(f'Operational driver failed: {script}, exit {code}')

    def wait_closed(self, attempt):
        exit_path = self.activity / 'formal' / attempt / 'native-exit.json'
        if self.process is not None:
            while self.process.alive():
                self.heartbeat()
                time.sleep(2)
            self.process.close()
            self.process = None
        if not exit_path.is_file():
            raise RuntimeError('Controller terminal/missing but no native exit; no restart permitted')
        if read(exit_path)['exit_code'] not in (0, 1):
            raise RuntimeError('Unexpected native exit; manual reconciliation required')
        for start in (self.activity / 'formal').glob('scoring_execution_*/start.json'):
            if not (start.parent / 'native-exit.json').is_file():
                raise RuntimeError('Another formal controller is not closed')

    def audit(self, attempt, prior):
        path = self.activity / 'audit' / (attempt + '_closure_001') / 'receipt.json'
        if not path.exists():
            self.require('audit-v4-closed-scoring.py', ['--attempt', attempt, '--prior', prior])
        value = read(path)
        native = self.activity / 'formal' / attempt / 'native-exit.json'
        if sha(native) != value['native_exit_sha256']:
            raise ValueError('Changed native closure')
        for rel, digest in value['bound_files_sha256'].items():
            if sha(self.activity / rel) != digest:
                raise ValueError('Previously attempted score bytes changed')
        self.latest = value['completed_scores']
        self.event('closure_verified', attempt=attempt, completed=self.latest,
                   remaining=PLANNED-self.latest, receipt_sha256=sha(path))
        return value

    def prepare_next(self):
        numbers = [int(p.name.rsplit('_', 1)[1]) for p in (self.activity / 'setup').glob('grading_transport_*')]
        number = max(numbers) + 1
        self.require('prepare-v4-formal-grading-amendment.py', ['--number', number])
        return number

    def probe(self, number):
        code = self.run('probe-v4-grading-sse-load.py', ['--number', number, '--http-error-evidence'])
        folder = self.activity / 'diagnosis' / f'proxy_grading_sse_load_{number:03d}'
        value = read(folder / 'receipt.json')
        rows = value['results']
        expected = {(m, i) for m in ('qwen3-8b', 'qwen3-14b') for i in range(16)}
        passed = code == 0 and len(rows) == 32 and {(r['model'], r['index']) for r in rows} == expected
        passed = passed and all(r['status'] == 'response' for r in rows)
        permanent = any(read(p).get('http_status') in (401, 403)
                        for p in folder.glob('*/*/requests/00.json'))
        self.event('probe_closed', number=number, passed=passed, permanent_rejection=permanent)
        return dict(passed=passed, permanent_rejection=permanent)

    def archive_probe(self):
        numbers = [int(p.parent.name.rsplit('_', 1)[1])
                   for p in (self.activity / 'archives').glob('operational_prefix_*/manifest.json')]
        self.archive_number = max(numbers) + 1
        self.require('archive-v4-operational-delta.py', ['--number', self.archive_number])

    def cooldown(self):
        self.event('probe_recovery_cooldown', seconds=30)
        for _ in range(15):
            time.sleep(2)
            self.heartbeat()

    def score(self, number, prior, existing):
        attempt = f'scoring_execution_{number:03d}'
        observed = False
        def observe(line):
            nonlocal observed
            if not observed and "'status': 'judged'" in line:
                self.require('seal-v4-grading-continuation.py', ['--number', number, '--prior', prior])
                self.require('update-v4-grading-continuation-status.py',
                             ['--number', number, '--prior', prior, '--operational-archive', self.archive_number])
                observed = True
        code = self.run('run-v4-formal-scores.py',
                        ['--number', number, '--attempt', attempt, '--continue-unattempted'], observe)
        if code not in (0, 1):
            raise RuntimeError('Unexpected scoring process exit')
        return attempt


@contextmanager
def exclusive_supervisor_lease(path):
    import msvcrt
    with path.open('a+b') as lease:
        if lease.tell() == 0:
            lease.write(b'0')
            lease.flush()
        lease.seek(0)
        msvcrt.locking(lease.fileno(), msvcrt.LK_NBLCK, 1)
        try:
            yield
        finally:
            lease.seek(0)
            msvcrt.locking(lease.fileno(), msvcrt.LK_UNLCK, 1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--registration', type=Path, required=True)
    args = parser.parse_args()
    config = read(args.registration)
    if config['planned'] != PLANNED or config['workers_per_model'] != 16:
        raise ValueError('Unexpected original grading scope')
    lock_path = Path(config['workspace']) / '.local/chapter2-grading-supervisor.lock'
    with exclusive_supervisor_lease(lock_path):
        process = None
        if config['attach_pid'] is not None:
            process = WindowsProcess(config['attach_pid'], config['attach_creation_filetime'])
        elif not (Path(config['workspace']) / config['activity'] / 'formal' /
                  config['attach_attempt'] / 'native-exit.json').is_file():
            raise RuntimeError('No bound live process or authoritative native exit')
        backend = Backend(args.registration, process)
        backend.check_sources()
        with (backend.folder / 'start.json').open('x', encoding='utf-8') as f:
            json.dump(dict(created_utc=datetime.now(timezone.utc).isoformat(), pid=os.getpid(),
                           registration_sha256=sha(args.registration)), f, indent=2)
        backend.event('supervisor_started', pid=os.getpid(), attached_pid=config['attach_pid'],
                      planned=PLANNED, original_scores_reissued=False)
        try:
            result = supervise(backend, config['attach_attempt'], config['prior_attempt'])
            receipt = dict(completed_utc=datetime.now(timezone.utc).isoformat(),
                           complete=True, scored=result['completed_scores'], planned=PLANNED,
                           old_requests_reissued=False, final_quality_analysis_completed=False)
            with (backend.folder / 'completion.json').open('x', encoding='utf-8') as f:
                json.dump(receipt, f, indent=2)
            backend.event('all_grading_closed', **receipt)
        except Exception as exc:
            receipt = dict(stopped_utc=datetime.now(timezone.utc).isoformat(),
                           complete=False, error_type=type(exc).__name__, reason=str(exc),
                           latest_completed=backend.latest, old_requests_reissued=False)
            with (backend.folder / 'stopped.json').open('x', encoding='utf-8') as f:
                json.dump(receipt, f, indent=2)
            backend.event('supervisor_stopped', **receipt)
            raise


if __name__ == '__main__':
    main()
