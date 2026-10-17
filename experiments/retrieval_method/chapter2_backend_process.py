"""Deterministic retrieval workers with one method per guarded process.

Workers do not call language models. The controller starts them before installing
its own no-subprocess input guard; each worker installs that guard independently.
"""
import argparse
import contextlib
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import RLock
import time


class BackendProcess:
    def __init__(self, method, resources, questions, *, context_characters=2400, parent_ratio=.5, context_policy=None):
        self.lock = RLock()
        env = dict(os.environ, PYTHONIOENCODING='utf-8', PYTHONUNBUFFERED='1')
        args = [sys.executable, str(Path(__file__).resolve()), '--method', method,
                '--resources', str(resources), '--questions', str(questions),
                '--context-characters', str(context_characters), '--parent-ratio', str(parent_ratio)]
        if context_policy is not None:args += ['--context-policy', context_policy]
        started = time.monotonic()
        self.process = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            text=True, encoding='utf-8', env=env,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        try:
            self.receipt = self._receive()
            if self.receipt.get('ready') is not True:raise RuntimeError('Backend initialization failed: ' + repr(self.receipt))
            self.receipt['controller_observed_startup_seconds'] = time.monotonic() - started
        except BaseException:
            self.close()
            raise

    def _receive(self):
        line = self.process.stdout.readline()
        if not line:raise RuntimeError('Retrieval worker terminated before returning a response')
        value = json.loads(line)
        if 'error' in value:raise RuntimeError(value['error'])
        return value

    def search(self, query, limit):
        with self.lock:
            self.process.stdin.write(json.dumps(dict(query=query, limit=limit), ensure_ascii=False) + '\n')
            self.process.stdin.flush()
            return self._receive()

    def close(self):
        if self.process.poll() is None:
            if self.process.stdin:self.process.stdin.close()
            try:self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                self.process.wait(timeout=10)
        if self.process.stdout:self.process.stdout.close()


class RemoteBackend:
    def __init__(self, server):
        self.server = server
        self.events = []

    def search(self, query, limit):
        result = self.server.search(query, limit)
        self.events.append(result['event'])
        return result['rows']


def serve(args):
    from chapter2_knowledge_input_guard import install
    guard = install(args.questions)
    # Reserve stdout for JSON RPC even when a dependency emits progress messages.
    with contextlib.redirect_stdout(sys.stderr):
        from chapter2_knowledge_backends_v4 import backend, GRAPH_ABLATIONS
        resources = json.loads(args.resources.read_text(encoding='utf-8'))
        engine = backend(args.method, resources, context_characters=args.context_characters, parent_ratio=args.parent_ratio)
    forbidden = [name for name in ('chapter2_baseline_native', 'sentence_transformers', 'torch') if name in sys.modules]
    graph = args.method == 'graph' or args.method in GRAPH_ABLATIONS
    if graph and forbidden:raise RuntimeError('Graph process imported baseline dependencies: ' + repr(forbidden))
    if graph and args.context_policy is not None and args.method not in {'no_context','adjacent_only','parent_blanket','parent_adaptive'}:
        engine.engine.context_policy = args.context_policy
    print(json.dumps(dict(ready=True, method=args.method, pid=os.getpid(), input_guard=guard,
        graph_process=graph, baseline_dependencies_loaded=forbidden,
        context_policy=engine.engine.context_policy if graph else None)), flush=True)
    for line in sys.stdin:
        try:
            request = json.loads(line)
            if set(request) != {'query', 'limit'} or not isinstance(request['query'], str) or not isinstance(request['limit'], int):
                raise ValueError('Only a query and integer limit are accepted')
            if not 1 <= request['limit'] <= 64:raise ValueError('Invalid retrieval limit')
            with contextlib.redirect_stdout(sys.stderr):
                rows = engine.search(request['query'], request['limit'])
            event = engine.events.pop()
            if engine.events:raise RuntimeError('Worker event log was not drained')
            print(json.dumps(dict(rows=rows, event=event), ensure_ascii=False), flush=True)
        except Exception as exc:
            print(json.dumps(dict(error=f'{type(exc).__name__}: {exc}')), flush=True)
            raise


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--method', required=True)
    parser.add_argument('--resources', type=Path, required=True)
    parser.add_argument('--questions', type=Path, required=True)
    parser.add_argument('--context-characters', type=int, default=2400)
    parser.add_argument('--parent-ratio', type=float, default=.5)
    parser.add_argument('--context-policy', choices=['adaptive','adjacent','blanket'])
    serve(parser.parse_args())
