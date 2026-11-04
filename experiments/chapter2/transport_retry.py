"""Durable transport retries. A received model response is never content-retried."""
from contextlib import contextmanager
from dataclasses import dataclass, asdict
from pathlib import Path
from copy import deepcopy
import json, math, shutil, sys, threading, time
from models import Client, encoded, sha, now, public_deployment, strict_json

RETRYABLE = {'outcome_unknown', 'http_result_unknown', 'deployment_halted', 'in_flight'}

@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    timeout_seconds: float = 600
    backoff_seconds: tuple = (5, 15)

    def __post_init__(self):
        if type(self.max_attempts) is not int or not 1 <= self.max_attempts <= 10:
            raise ValueError('Expected 1..10 transport attempts')
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError('Positive finite timeout required')
        if len(self.backoff_seconds) < self.max_attempts - 1 or any(not math.isfinite(x) or not 0 <= x <= 300 for x in self.backoff_seconds):
            raise ValueError('Bounded backoff required')

    def public(self):
        fields=asdict(self);fields['backoff_seconds']=list(fields['backoff_seconds'])
        return dict(**fields, retry_http_statuses=[408, 429, '5xx'],
                    response_selection='first_received_response_without_content_selection',
                    interrupted_attempt='preserve_as_unknown_then_retry',
                    exhausted='retain_unresolved_and_halt_model',
                    unknown_prior_server_work='may_have_completed; usage_remains_unknown')

def retryable(row):
    return row['status'] in RETRYABLE or (row['status'] == 'http_rejected' and row.get('http_status') in {408, 429})

def attempt_cost(row):
    # A killed process may not have flushed the transmitted flag. Charge it once,
    # while retaining the uncertainty in the attempt record and usage report.
    return 1 if row['status'] == 'in_flight' else row['transport_attempts']

def storage_path(path):
    """Use Windows extended paths for durable artifacts, including future full runs."""
    path=Path(path).absolute()
    if sys.platform=='win32':
        value=str(path)
        if not value.startswith('\\\\?\\'):
            value='\\\\?\\UNC\\'+value[2:] if value.startswith('\\\\') else '\\\\?\\'+value
        return Path(value)
    return path

@contextmanager
def request_lock(path):
    """Kernel lock survives stale files, releases on process exit, rejects live owners."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix('.lock').open('a+b') as handle:
        if handle.tell() == 0: handle.write(b'0'); handle.flush()
        handle.seek(0)
        if sys.platform == 'win32':
            import msvcrt
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try: yield
        finally:
            handle.seek(0)
            if sys.platform == 'win32': msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else: fcntl.flock(handle, fcntl.LOCK_UN)

def atomic(path, row):
    temp = path.with_suffix('.new'); temp.write_bytes(encoded(row)); temp.replace(path)

class RetryingClient:
    can_resume = True

    def __init__(self, deployment, policy=None, *, concurrency=None, sleeper=time.sleep, factory=Client):
        self.deployment = deployment; self.policy = policy or RetryPolicy()
        self.concurrency = deployment.concurrency if concurrency is None else concurrency
        if type(self.concurrency) is not int or not 1 <= self.concurrency <= deployment.concurrency:
            raise ValueError('Invalid effective concurrency')
        self.halted = threading.Event(); self.limiter = threading.BoundedSemaphore(self.concurrency)
        self.sleeper = sleeper; self.factory = factory

    def _check(self, row, body):
        if row['request_sha256'] != sha(encoded(body)) or row['request'] != body:
            raise ValueError('Resume request changed; no request submitted')
        if row['deployment'] != public_deployment(self.deployment):
            raise ValueError('Resume deployment changed; no request submitted')

    def _attempts(self, path, body):
        folder = path.parent / 'attempts' / path.stem
        folder.mkdir(parents=True, exist_ok=True)
        entries = []
        for i, p in enumerate(sorted(folder.glob('*.json'))):
            if p.name != f'{i:03d}.json': raise ValueError('Non-contiguous attempt ledger')
            row = strict_json(p.read_bytes()); self._check(row, body)
            if row['status'] == 'response':
                wire = p.with_suffix('.response.bin')
                if sha(wire.read_bytes()) != row['response_sha256'] or strict_json(wire.read_bytes()) != row['raw_response']:
                    raise ValueError('Response body drift')
            entries.append((p, row))
        return folder, entries

    def _publish(self, path, entries, *, exhausted=False):
        selected_path, selected = entries[-1]
        row = deepcopy(selected)
        if selected['status']=='response_persistence_error':
            # Existing scoring contracts already treat runner_error as unknown.
            # Keep the specific failure in the immutable attempt and the cause.
            row.update(status='runner_error',infrastructure_cause='response_persistence_error')
        row.update(transport_attempts=sum(attempt_cost(r) for _, r in entries),
                   retry_policy=self.policy.public(), retry_exhausted=exhausted,
                   attempts=[dict(record_file=p.relative_to(path.parent).as_posix(), record_sha256=sha(p.read_bytes()),
                                  status=r['status'], transmitted=None if r['status']=='in_flight' else r['transport_attempts'], origin=r.get('origin', 'network')) for p, r in entries])
        if selected.get('response_sha256') and selected['status']!='response_persistence_error':
            wire = selected_path.with_suffix('.response.bin'); dst = path.with_suffix('.response.bin')
            if dst.exists() and dst.read_bytes() != wire.read_bytes(): raise ValueError('Never replace an existing response')
            if not dst.exists(): shutil.copyfile(wire, dst)
            row['response_body_file'] = dst.name
        atomic(path, row)
        if selected['status'] in {'model_identity_mismatch','response_persistence_error'} or exhausted: self.halted.set()
        return row

    def complete(self, body, path=None):
        if path is None: raise ValueError('Durable request path required for automatic retry')
        if body.get('model') != self.deployment.model or body.get('stream') is not False:
            raise ValueError('Request identity mismatch')
        path = storage_path(path)
        with request_lock(path):
            folder, entries = self._attempts(path, body)
            if path.exists():
                previous = strict_json(path.read_bytes()); self._check(previous, body)
                if not entries: raise ValueError('Missing attempt ledger; import legacy requests explicitly')
                # A received response, even malformed or truncated, is final for transport.
                if not retryable(previous):
                    if previous.get('retry_exhausted'): self.halted.set()
                    return self._publish(path, entries)
            for i, (_, row) in enumerate(entries):
                if not retryable(row):
                    if i != len(entries) - 1: raise ValueError('Attempt after a received terminal response')
                    return self._publish(path, entries)
            attempts = sum(attempt_cost(r) for _, r in entries)
            while attempts < self.policy.max_attempts:
                if self.halted.is_set():
                    if entries: return self._publish(path, entries, exhausted=True)
                    p=folder/'000.json';row=dict(deployment=public_deployment(self.deployment),request=body,request_sha256=sha(encoded(body)),status='deployment_halted',transport_attempts=0,started_utc=now(),ended_utc=now(),seconds=0)
                    p.write_bytes(encoded(row));entries.append((p,row))
                    return self._publish(path, entries, exhausted=True)
                if attempts:
                    self.sleeper(self.policy.backoff_seconds[min(attempts - 1, len(self.policy.backoff_seconds) - 1)])
                attempt_path = folder / f'{len(entries):03d}.json'
                # A fresh one-attempt client cannot halt unrelated requests before retry exhaustion.
                with self.limiter:
                    client = self.factory(self.deployment, timeout=self.policy.timeout_seconds)
                    row = client.complete(body, attempt_path)
                entries.append((attempt_path, row)); attempts += row['transport_attempts']
                if not retryable(row): return self._publish(path, entries)
                self._publish(path, entries)  # crash-safe progress, not a task result
            return self._publish(path, entries, exhausted=True)

def import_request(source, target):
    """Copy a sealed legacy request into a new recovery workspace, without changing it."""
    source, target = storage_path(source), storage_path(target)
    row = strict_json(source.read_bytes())
    if row['status'] not in {'response', 'outcome_unknown', 'http_result_unknown', 'deployment_halted', 'in_flight'}:
        raise ValueError('Only received prefixes or interrupted transport may be imported')
    with request_lock(target):
        folder = target.parent / 'attempts' / target.stem
        if folder.exists():
            first = strict_json((folder/'000.json').read_bytes())
            if first.get('imported_record_sha256') != sha(source.read_bytes()): raise ValueError('Imported prefix changed')
            return
        if target.exists(): raise FileExistsError('Request exists without its import ledger')
        folder.mkdir(parents=True, exist_ok=False)
        attempt = folder / '000.json'
        imported = dict(row, origin='imported', imported_record_sha256=sha(source.read_bytes()))
        attempt.write_bytes(encoded(imported))
        if row['status'] == 'response':
            wire = source.with_suffix('.response.bin')
            if sha(wire.read_bytes()) != row['response_sha256']: raise ValueError('Imported wire drift')
            shutil.copyfile(wire, attempt.with_suffix('.response.bin'))
            shutil.copyfile(wire, target.with_suffix('.response.bin'))
        atomic(target, imported)
