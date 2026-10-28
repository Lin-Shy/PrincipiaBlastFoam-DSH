"""Operational envelope for the byte-preserved frozen Test160 executors.

No prompt/backend/scoring changes. Definite transient HTTP failures alone may
retry; uncertain transport outcomes are held. Model validity failures isolate
the affected service before another request can be sent.
"""
import argparse
import json
from pathlib import Path
import threading
import time
import traceback
import http.client

import test160_runner as runner
import dev40_supplement as transport
import single_pass_dev40 as s

BASE = s.RUN / 'test160_runs'
ORIGINAL_CLIENT = transport.client
LOCK = threading.RLock()
GATES = {m: threading.Lock() for m in s.MODELS}
VERIFIED = set()
BLOCKED = {}
FATAL = {'model_identity_mismatch', 'provider_budget_violation', 'usage_unknown'}
RETRY_HTTP = {429, 500, 502, 503, 504}


class BranchBlocked(RuntimeError):
    pass


def extend_local_timeout():
    """Owner 2026-10-27: allow long 8B inference/queueing, same wire payload."""
    original = http.client.HTTPConnection
    from urllib.parse import urlsplit
    host = urlsplit(transport.Registry().resolve('qwen3_8b')['endpoint']).hostname
    class PatientSocket:
        def __init__(self, sock):
            self.sock = sock
        def __getattr__(self, name):
            return getattr(self.sock, name)
        def settimeout(self, value):
            return self.sock.settimeout(1200 if value == 600 else value)
    class PatientConnection(original):
        def connect(self):
            if self.host == host:
                self.timeout = 120
            super().connect()
            if self.host == host:
                self.sock = PatientSocket(self.sock)
    http.client.HTTPConnection = PatientConnection


def event(value):
    with LOCK:
        s.append(BASE / 'execution_events.jsonl', dict(utc=s.now(), **value))


def guarded_client(folder, model):
    original = ORIGINAL_CLIENT(folder, model)

    def perform(body, turn):
        with LOCK:
            if model in BLOCKED:
                raise BranchBlocked(model + ': ' + BLOCKED[model])
        start = time.monotonic()
        result = original(body, turn)
        for ordinal, delay in enumerate((5, 20), 1):
            if result.get('http_status') not in RETRY_HTTP:
                break
            event(dict(kind='definite_http_retry', model=model, folder=str(folder),
                       turn=turn, http_status=result['http_status'], attempt=ordinal + 1))
            time.sleep(delay)
            retry = folder / 'transport_recovery' / ('turn_%02d_attempt_%d' % (turn, ordinal))
            retry.mkdir(parents=True, exist_ok=False)
            result = ORIGINAL_CLIENT(retry, model)(body, turn)
        record = dict(kind='generation_request_completed', model=model, folder=str(folder),
                      turn=turn, status=result['status'], seconds=round(time.monotonic()-start, 3),
                      http_status=result.get('http_status'))
        raw = result.get('raw_response', {})
        record.update(response_model=raw.get('model'), usage=raw.get('usage'),
                      actual_cost={k: raw[k] for k in ('cost', 'billing', 'cost_details') if k in raw} or 'Unknown')
        event(record)
        if result['status'] in FATAL:
            with LOCK:
                BLOCKED[model] = result['status']
                s.save(BASE / ('STOP_' + model + '.json'), dict(utc=s.now(), **record))
        return result

    def call(body, turn):
        # A first real task verifies the service; it is retained as its normal answer.
        if model not in VERIFIED:
            with GATES[model]:
                result = perform(body, turn)
                if result['status'] == 'response':
                    VERIFIED.add(model)
                return result
        return perform(body, turn)
    return call


def main():
    p = argparse.ArgumentParser()
    p.add_argument('mode', choices=['agentic', 'single_pass'])
    p.add_argument('--authorization', type=Path, required=True)
    p.add_argument('--model', choices=['qwen3_8b', 'qwen3_14b'])
    a = p.parse_args()
    BASE.mkdir(parents=True, exist_ok=True)
    # Fail closed on a persisted identity/protocol stop across restarts.
    for model in s.MODELS:
        stop = BASE / ('STOP_' + model + '.json')
        if stop.exists():
            BLOCKED[model] = s.load(stop)['status']
    transport.client = guarded_client
    extend_local_timeout()
    if a.model:
        frozen_load = runner.load_frozen
        def scoped_load(*args, **kwargs):
            manifest, questions = frozen_load(*args, **kwargs)
            manifest['configurations'] = [c for c in manifest['configurations'] if c['model_key'] == a.model]
            return manifest, questions
        runner.load_frozen = scoped_load
        original_lock = runner.exclusive_lock
        runner.exclusive_lock = lambda path: original_lock(path.with_name('generation_' + a.model + '.lock'))
    event(dict(kind='executor_start', mode=a.mode, pid=__import__('os').getpid(),
               authorization_sha256=s.sha(a.authorization), source_sha256=s.sha(Path(__file__)),
               frozen_runner_sha256=s.sha(Path(runner.__file__))))
    try:
        if a.mode == 'agentic':
            runner.execute(a.authorization)
        else:
            runner.execute_single_pass(a.authorization)
    except Exception as exc:
        event(dict(kind='executor_error', mode=a.mode, error_type=type(exc).__name__))
        traceback.print_exc()
        raise
    event(dict(kind='executor_finished', mode=a.mode))


if __name__ == '__main__':
    main()
