"""Continue an interrupted local readout session, charging one exact retransmission."""
import hashlib
import json
import os
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit

from cluster_first import RetryGate
from local_first_wave import (HERE, base, batch, common_environment, launch_attempt,
                              read, runtime, sha, snapshot_runtime, write)
import model_budget


def resume_unanswered(root, short, arm, pins):
    policy = read(batch/'authorization.json')
    if (root.parent.parent != batch/'local_recheck_100'
            or f'{short}/{arm}' not in policy['local_replacements']['new_arms']
            or policy['local_replacements']['cluster_jobs'] != 0):
        raise PermissionError('not a selected local arm')
    binding = read(base/'pilot_decision_20261117'/f'{arm}.binding.json')
    binding.pop('cluster', None)
    grant = read(root/'attempt_intent.json')['authorization']
    launch_attempt.check(root.parent, arm, binding, grant)
    if grant['max_requests_per_arm'] != policy['requests_per_arm'] or any(sha(Path(p)) != h for p, h in pins.items()):
        raise ValueError('budget or system version changed')
    snapshot_runtime.verify(runtime)
    history = read(root/'provider_ledger/ledger.json')['events']
    offset = len(history)
    last = history[-1]
    if (not 0 < offset < grant['max_requests_per_arm'] or last['request'] != offset
            or last['state'] != 'unknown' or last.get('error_type') != 'IncompleteRead'
            or last.get('retry_disposition') or (offset > 1 and history[-2].get('retry_disposition'))
            or (root/f'provider_ledger/response-{offset:04d}.bin').exists()):
        raise RuntimeError('no eligible unretried truncated response')
    original = read(root/f'provider_ledger/request-{offset:04d}.json')
    outcome = read(root/'native_outcome.json')
    records = [json.loads(line) for line in (root/'native_events.jsonl').read_bytes().splitlines()]
    events = [r['event'] for r in records]
    calls = Counter(e['data']['callId'] for e in events if e['type']=='tool/call')
    results = Counter(e['data']['message']['source']['callId'] for e in events if e['type']=='tool/result')
    last_step = max(i for i,e in enumerate(events) if e['type']=='step/start')
    if (set(r['session_id'] for r in records) != {outcome['session_id']}
            or outcome['reason']['kind'] != 'error' or calls != results
            or any(n != 1 for n in calls.values())
            or any(e['type'] in ('assistant/message','tool/call') for e in events[last_step:])):
        raise RuntimeError('model output or tool action requires reconciliation')
    creds = {}
    for line in Path(binding['credential_file']).read_text(encoding='utf-8-sig').splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            key, val = line.split('=',1)
            creds[key.strip()] = val.strip().strip('"').strip("'")
    endpoint = creds['CHAPTER3_BASE_URL'].rstrip('/')
    url = urlsplit(endpoint)
    if (url.scheme != 'https' or not url.hostname or url.username or url.password
            or hashlib.sha256(endpoint.encode()).hexdigest() != grant['endpoint_sha256']
            or creds['CHAPTER3_MODEL'] != grant['model'] or original['model'] != grant['model']):
        raise PermissionError('provider binding mismatch')
    class ContinuationGate(RetryGate):
        def call(self, body):
            if len(self.events) == offset:
                requested = {t['function']['name'] for t in body.get('tools', [])}
                original_tools = {t['function']['name'] for t in original.get('tools', [])}
                if body.get('model') != original['model'] or requested != original_tools:
                    raise ValueError('resumed model or tools changed')
                # The previous response never reached DSH. Send the original body exactly once.
                return model_budget.Gate.call(self, original)
            return super().call(body)

    destination = root/'retry'
    lock = runtime.parent/'chapter3-model.lock'
    with lock.open('x', encoding='utf8') as stream:
        json.dump(dict(pid=os.getpid(), pair=str(root.parent), arm=arm),stream)
    server = None
    try:
        destination.mkdir(exist_ok=False)
        gate = ContinuationGate(destination/'provider_ledger', grant['model'], grant['max_requests_per_arm'],
                                grant['max_output_tokens'], model_budget.upstream(endpoint, creds['CHAPTER3_API_KEY'], 180),
                                grant['generation'])
        gate.events.extend(history)
        gate.events[-1] = dict(last, retry_disposition='one new counted request on same task')
        gate.save()
        server = model_budget.serve(gate)
        overlay = read(root/'approved.patch.yml')
        overlay[0]['config']['providers']['chapter3-approved']['baseURL'] = f'http://127.0.0.1:{server.server_port}/v1'
        write(destination/'overlay.json',overlay)
        prompt = destination/'continue.txt'
        prompt.write_text('继续原任务。',encoding='utf8')
        write(destination/'intent.json',dict(session_id=outcome['session_id'],offset=offset,cap=gate.limit,
              tool_results=sum(results.values()),retry_of=offset,cluster_jobs=0))
        env = dict(common_environment(root), C3_PYTHON=sys.executable, C3_MODULE_PATH=str(HERE.parent),
                   C3_RUNTIME=str(runtime), C3_GATE_TOKEN=gate.token)
        cmd = [launch_attempt.runtime_node(runtime),str(HERE/'native_resume.mjs'),str(root),
               str(runtime),str(destination/'overlay.json'),str(prompt),outcome['session_id']]
        earlier = read(root/'attempt_exit.json')['wall_seconds']
        start = time.monotonic()
        with (destination/'stdout.log').open('xb') as out, (destination/'stderr.log').open('xb') as err:
            try:
                code = subprocess.run(cmd,cwd=root/'workspace',env=env,stdout=out,stderr=err,
                                      timeout=max(1,grant['wall_seconds']-earlier)).returncode
            except subprocess.TimeoutExpired:
                code = 1
        elapsed = time.monotonic()-start
        exact = (destination/f'provider_ledger/request-{offset+1:04d}.json')
        write(destination/'attempt_exit.json',dict(exit_code=code,wall_seconds=earlier+elapsed,
              resumed_seconds=elapsed,exact_retransmission=exact.is_file() and read(exact)==original))
        return code
    finally:
        if server:
            server.shutdown()
            server.server_close()
        if read(lock)['pid'] == os.getpid():
            lock.unlink()
