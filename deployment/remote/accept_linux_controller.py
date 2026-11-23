"""Offline agent-loop acceptance through normal dsh profile and local fake SSE.

The fixed fixture requests one file write and one harmless shell command.
No provider credential or scheduler client is used.
"""
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import threading
import time
import re
import sys

root = Path(os.environ['CONTROLLER_ROOT']).resolve()
run_name = sys.argv[1] if len(sys.argv) > 1 else 'offline-acceptance-01'
professional = '--professional' in sys.argv[2:]
assert re.fullmatch(r'offline-acceptance-[0-9]{2}', run_name)
run = root / 'runs' / run_name
run.mkdir(mode=0o700)
requests = []
request_lock = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        with request_lock:
            requests.append(body)
            number = len(requests)
            (run / 'local-model-requests.json').write_text(json.dumps(requests, indent=2))
        if number > 3:
            self.send_error(429, 'Offline fixture exhausted')
            return
        if number == 1:
            delta = {'role': 'assistant', 'tool_calls': [{'index': 0, 'id': 'offline_write',
                'type': 'function', 'function': {'name': 'write',
                'arguments': json.dumps({'file_path': 'controller-marker.txt', 'content': 'offline-controller-ok\n'})}}]}
            finish = 'tool_calls'
        elif number == 2:
            delta = {'role': 'assistant', 'tool_calls': [{'index': 0, 'id': 'offline_bash',
                'type': 'function', 'function': {'name': 'bash',
                'arguments': json.dumps({'command': "printf 'offline-shell-ok\\n'", 'description': 'Harmless Linux deployment check'})}}]}
            finish = 'tool_calls'
        else:
            delta = {'role': 'assistant', 'content': 'offline-agent-ok'}
            finish = 'stop'
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-cache')
        self.end_headers()
        for value, reason in ((delta, None), ({}, finish)):
            chunk = {'id': 'offline-' + str(number), 'object': 'chat.completion.chunk',
                     'created': int(time.time()), 'model': 'controller-offline',
                     'choices': [{'index': 0, 'delta': value, 'finish_reason': reason}]}
            if reason:
                chunk['usage'] = {'prompt_tokens': 10, 'completion_tokens': 5, 'total_tokens': 15}
            self.wfile.write(('data: ' + json.dumps(chunk) + '\n\n').encode())
        self.wfile.write(b'data: [DONE]\n\n')
        self.wfile.flush()


server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
thread = threading.Thread(target=server.serve_forever, daemon=True)
thread.start()
patch = [
    {'id': 'session-title-llm', 'disabled': True},
    {'id': 'skill-filesystem', 'config': {'includeDefaultRoots': False}},
    {'id': 'llm-deepseek', 'disabled': True},
    {'id': 'llm-pi-ai', 'config': {'providers': {'controller-offline': {
        'api': 'openai-completions', 'apiKeyEnv': 'CONTROLLER_OFFLINE_KEY',
        'baseURL': 'http://127.0.0.1:' + str(server.server_port) + '/v1',
        'models': [{'id': 'controller-offline', 'contextWindow': 32768,
                    'maxTokens': 1024, 'input': ['text']}],
        'timeoutMs': 15000, 'retryPolicy': {'mode': 'normal', 'maxRetries': 0}}}}},
    {'id': 'agent-default-model', 'config': {'provider': 'controller-offline', 'model': 'controller-offline'}},
    {'id': 'sandbox-policy', 'config': {'mode': 'danger-full-access', 'workspaceRoot': str(run)}},
    {'id': 'approval', 'config': {'policy': 'never'}},
]
if professional:
    professional_patch = json.loads((root / 'application/professional.patch.json').read_text())
    patch = [item for item in patch if item['id'] != 'skill-filesystem'] + professional_patch
(run / 'offline.patch.yml').write_text(json.dumps(patch, indent=2))
environment = {k: v for k, v in os.environ.items() if not any(word in k.upper() for word in ('API_KEY', 'TOKEN', 'SECRET', 'PASSWORD'))}
environment.update(HOME=str(root / 'home'), DSH_HOME=str(root / 'dsh-home'),
                   DSH_AGENTS_HOME=str(root / 'agents-home'),
                   TMPDIR=str(root / 'tmp'), XDG_CACHE_HOME=str(root / 'cache'),
                   DSH_TELEMETRY_MODE='DISABLED', CONTROLLER_OFFLINE_KEY='offline-fixture-only',
                   PATH=str(root / 'bin') + ':' + os.environ.get('PATH', '/usr/bin:/bin'),
                   ENABLE_EXECUTION='false', REQUIRE_EXECUTION='false')
if professional:
    environment.update(C3_RUNTIME=str(root / 'source'), C3_MODULE_PATH=str(root / 'application'),
                       C3_PYTHON=os.environ['npm_config_python'])
summary = {'paid_model_calls': 0, 'node_jobs': 0, 'fixture': 'fixed local SSE; no model inference',
           'normal_profile_attempted': True, 'passed': False}
try:
    with (run / 'stdout.log').open('w') as out, (run / 'stderr.log').open('w') as err:
        process = subprocess.run([str(root / 'bin/node'), str(root / 'source/apps/cli/lib/bin.js'),
            '--profile', 'headless', '--patch', str(run / 'offline.patch.yml'),
            'Run the fixed offline maintenance fixture. Do not run simulation or use any network service.'],
            cwd=run, env=environment, stdout=out, stderr=err, timeout=120)
    summary.update(exit_code=process.returncode, local_fixture_requests=len(requests))
    if professional:
        available = {item['function']['name'] for item in requests[0].get('tools', [])}
        expected = {'pressure_window', 'convert_volume_rates', 'interval_coverage', 'latest_attempt_events'}
        summary['professional_tools_present'] = expected.issubset(available)
        prompt = json.dumps(requests[0].get('messages', []))
        summary['professional_skills_listed'] = all(name in prompt for name in (
            'engineering-delivery', 'measurement-review', 'blastfoam-quality-review'))
    marker = run / 'controller-marker.txt'
    summary['marker_correct'] = marker.exists() and marker.read_text() == 'offline-controller-ok\n'
    tool_messages = [m for request in requests for m in request.get('messages', []) if m.get('role') == 'tool']
    summary['shell_result_seen'] = any('offline-shell-ok' in json.dumps(m) for m in tool_messages)
    summary['session_files'] = [str(p.relative_to(root)) for p in (root / 'dsh-home').rglob('*.jsonl*')]
    summary['passed'] = (process.returncode == 0 and len(requests) == 3 and summary['marker_correct']
                         and summary['shell_result_seen'] and bool(summary['session_files']))
    if professional:
        summary['passed'] = summary['passed'] and summary['professional_tools_present'] and summary['professional_skills_listed']
except Exception as error:
    summary['error'] = type(error).__name__ + ': ' + str(error)
finally:
    server.shutdown()
    (run / 'summary.json').write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary), flush=True)
