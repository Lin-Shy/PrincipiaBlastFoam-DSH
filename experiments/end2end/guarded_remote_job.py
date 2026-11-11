"""Linux-only detached job guard. No shell, model calls, or solver modifications.

Start and status calls are short; the worker survives SSH/Agent Host teardown.
The memory bound is RLIMIT_AS per process (inherited by children), not a claim
of an aggregate cgroup RSS bound. Production blastFoam must stay serial.
"""
from pathlib import Path
import argparse
import datetime
import json
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import time

MIB = 1024 ** 2


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def write(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n', encoding='utf-8')
    os.replace(temporary, path)


def anomaly(text):
    for line in text.splitlines():
        if re.search(r'\b(?:nan|[+-]?inf(?:inity)?)\b|FOAM FATAL|segmentation fault', line, re.I):
            return {'kind': 'nonfinite_or_fatal', 'line': line}
        match = re.search(r'min\(T\):\s*([-+0-9.eE]+)', line)
        if match and float(match.group(1)) <= 0:
            return {'kind': 'nonpositive_temperature', 'line': line}
    return None


def tree_bytes(root):
    total = 0
    for directory, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = [d for d in dirs if not (Path(directory) / d).is_symlink()]
        for name in names:
            path = Path(directory) / name
            if not path.is_symlink():
                try:
                    total += path.stat().st_size
                except FileNotFoundError:
                    pass
    return total


def terminate(child):
    if child.poll() is not None:
        return
    try:
        os.killpg(child.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        child.wait(timeout=2)
    except subprocess.TimeoutExpired:
        os.killpg(child.pid, signal.SIGKILL)
        child.wait()


def worker(job):
    import fcntl
    import resource

    cfg = json.loads((job / 'request.json').read_text(encoding='utf-8'))
    root = Path(cfg['workspace'])
    ledger_path = root / '.guard_usage.json'
    state = {'status': 'preflight', 'started_utc': now(), 'command': cfg['command'],
             'accuracy_scoring': False, 'solver_modified': False,
             'memory_limit_kind': 'inherited per-process RLIMIT_AS, not aggregate RSS',
             'memory_limit_bytes': cfg['memory_mib'] * MIB,
             'file_size_limit_bytes': cfg['file_size_mib'] * MIB}
    child = None
    started = None
    used = 0.0
    lock = (root / '.guard_usage.lock').open('a')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if ledger_path.exists():
            ledger = json.loads(ledger_path.read_text(encoding='utf-8'))
            used = ledger['charged_wall_seconds']
            if ledger.get('model_anomaly_stop'):
                state.update(status='blocked', reason='prior_model_anomaly_no_restart')
                return
        remaining = cfg['budget_seconds'] - used
        if remaining <= 0:
            state.update(status='blocked', reason='cumulative_wall_budget_exhausted')
            return
        timeout = min(cfg['timeout_seconds'], remaining)
        if shutil.disk_usage(root).free < cfg['minimum_free_mib'] * MIB:
            state.update(status='blocked', reason='insufficient_free_disk')
            return
        if tree_bytes(root) > cfg['storage_mib'] * MIB:
            state.update(status='blocked', reason='workspace_storage_budget')
            return
        cpu = min(os.sched_getaffinity(0))

        def limits():
            os.setsid()
            os.sched_setaffinity(0, {cpu})
            cap = cfg['memory_mib'] * MIB
            resource.setrlimit(resource.RLIMIT_AS, (cap, cap))
            file_cap = cfg['file_size_mib'] * MIB
            resource.setrlimit(resource.RLIMIT_FSIZE, (file_cap, file_cap))
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

        started = time.monotonic()
        with (job / 'process.log').open('wb') as output:
            child = subprocess.Popen(cfg['command'], cwd=cfg['cwd'], stdin=subprocess.DEVNULL,
                                     stdout=output, stderr=subprocess.STDOUT, preexec_fn=limits)
            state.update(status='running', pid=child.pid, cpu_affinity=[cpu],
                         effective_timeout_seconds=timeout, prior_charged_wall_seconds=used)
            # preexec_fn has completed before Popen returns.
            try:
                state['proc_limits'] = Path(f'/proc/{child.pid}/limits').read_text()
                state['proc_status'] = [x for x in Path(f'/proc/{child.pid}/status').read_text().splitlines()
                                        if x.startswith(('Cpus_allowed_list:', 'VmRSS:', 'VmHWM:'))]
            except FileNotFoundError:
                state['process_observation'] = 'process already exited; child inherits enforced preexec limits'
            write(job / 'status.json', state)
            cursor = 0
            pending = ''
            disk_check = 0.0
            while True:
                with (job / 'process.log').open('rb') as source:
                    source.seek(cursor)
                    data = source.read()
                cursor += len(data)
                pending += data.decode('utf-8', errors='replace')
                lines = pending.splitlines(keepends=True)
                pending = '' if not lines or lines[-1].endswith(('\n', '\r')) else lines.pop()
                problem = anomaly(''.join(lines))
                elapsed = time.monotonic() - started
                if problem:
                    state.update(status='model_anomaly_stop', reason=problem)
                    terminate(child)
                    break
                if (job / 'STOP').exists():
                    state.update(status='operator_stop', reason='STOP marker')
                    terminate(child)
                    break
                if child.poll() is not None:
                    problem = anomaly(pending)
                    state.update(status='model_anomaly_stop' if problem else
                                 'process_completed' if child.returncode == 0 else 'process_failed')
                    if problem:
                        state['reason'] = problem
                    break
                if elapsed >= timeout:
                    state.update(status='timeout', reason='wall_budget')
                    terminate(child)
                    break
                if elapsed >= disk_check:
                    disk_check = elapsed + 1
                    if (shutil.disk_usage(root).free < cfg['minimum_free_mib'] * MIB
                            or tree_bytes(root) > cfg['storage_mib'] * MIB):
                        state.update(status='resource_stop', reason='disk_limit')
                        terminate(child)
                        break
                time.sleep(.1)
            state['exit_code'] = child.wait()
    except BlockingIOError:
        state.update(status='blocked', reason='another_guarded_job_active')
    except Exception as error:
        state.update(status='guard_failed', reason=f'{type(error).__name__}: {error}')
    finally:
        if child is not None:
            terminate(child)
        if started is not None:
            elapsed = time.monotonic() - started
            state['elapsed_seconds'] = elapsed
            write(ledger_path, {'charged_wall_seconds': used + elapsed, 'updated_utc': now(),
                                'model_anomaly_stop': state['status'] == 'model_anomaly_stop'})
        state['finished_utc'] = now()
        write(job / 'status.json', state)
        lock.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['start', 'status', 'worker'])
    parser.add_argument('--job', required=True, type=Path)
    parser.add_argument('--workspace', type=Path)
    parser.add_argument('--cwd', type=Path)
    parser.add_argument('--memory-mib', type=int, default=3072)
    parser.add_argument('--file-size-mib', type=int, default=512)
    parser.add_argument('--budget-seconds', type=float, default=5400)
    parser.add_argument('--timeout-seconds', type=float, default=5400)
    parser.add_argument('--minimum-free-mib', type=int, default=2048)
    parser.add_argument('--storage-mib', type=int, default=2048)
    argv = sys.argv[1:]
    split = argv.index('--') if '--' in argv else len(argv)
    command = argv[split + 1:]
    args = parser.parse_args(argv[:split])
    if sys.platform != 'linux':
        parser.error('Linux required for affinity and process limits')
    job = args.job.resolve()
    if args.action == 'worker':
        worker(job)
    elif args.action == 'status':
        print((job / 'status.json').read_text(encoding='utf-8'))
    else:
        if not args.workspace or not command or not args.cwd:
            parser.error('start requires --workspace, --cwd and -- command argv')
        root = args.workspace.resolve(strict=True)
        cwd = args.cwd.resolve(strict=True)
        if root not in job.parents or not cwd.is_relative_to(root):
            parser.error('job and cwd must stay inside workspace')
        for value in [args.memory_mib, args.file_size_mib, args.budget_seconds, args.timeout_seconds,
                      args.minimum_free_mib, args.storage_mib]:
            if not math.isfinite(value) or value <= 0:
                parser.error('resource bounds must be finite and positive')
        if not command:
            parser.error('empty command')
        job.mkdir(parents=True, exist_ok=False)
        cfg = {**vars(args), 'command': command, 'workspace': str(root), 'cwd': str(cwd), 'job': str(job)}
        write(job / 'request.json', cfg)
        write(job / 'status.json', {'status': 'queued', 'created_utc': now()})
        with (job / 'guard.log').open('wb') as output:
            process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), 'worker', '--job', str(job)],
                                       stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
                                       start_new_session=True, close_fds=True)
        print(json.dumps({'job': str(job), 'guard_pid': process.pid, 'status': 'queued'}))


if __name__ == '__main__':
    main()
