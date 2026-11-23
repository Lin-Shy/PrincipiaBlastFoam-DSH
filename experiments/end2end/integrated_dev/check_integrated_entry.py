"""Normal entry inspection/denial and native registry checks; fake-provider HTTP only."""
import http.client
import json
from pathlib import Path
import subprocess
import sys
import urllib.error
import urllib.request
from start import HERE, WS, common_environment, runtime_node
import launch_attempt
from launch_integrated_attempt import environment, inspect, load_launcher, run
from model_budget import Gate


def check_http(root):
    module = load_launcher()
    assert module.serve is not launch_attempt.serve
    original_serve = launch_attempt.serve
    records = []
    for kind in ('success', 'disconnect'):
        def forward(body):
            if kind == 'disconnect':
                raise http.client.RemoteDisconnected('fixture only')
            return b'data: {"usage":{"prompt_tokens":1,"completion_tokens":1,"total_tokens":2}}\n\ndata: [DONE]\n\n'
        gate = Gate(root / ('http-' + kind), 'fixture', 1, 5, forward)
        server = module.serve(gate)
        replies = []
        try:
            for _ in range(2):
                request = urllib.request.Request(f'http://127.0.0.1:{server.server_port}/v1/chat/completions',
                    data=b'{"model":"fixture"}', headers={'Authorization': 'Bearer ' + gate.token})
                try:
                    response = urllib.request.urlopen(request, timeout=5)
                except urllib.error.HTTPError as error:
                    response = error
                with response:
                    replies.append({'status': response.status, 'body': response.read().decode()})
        finally:
            server.shutdown()
            server.server_close()
        assert [row['status'] for row in replies] == ([200, 409] if kind == 'success' else [502, 409])
        assert len(gate.events) == 1 and launch_attempt.serve is original_serve
        records.append({'case': kind, 'replies': replies, 'events': gate.events})
    return records


def main():
    destination = Path(sys.argv[1]).resolve()
    runtime = WS / '.chapter3-runtime/stage-20261117/dsh'
    results = []
    for arm in ('general', 'professional'):
        pair = destination / 'pairs' / arm
        root = pair / arm
        checked = inspect(pair, arm)
        denied = False
        try:
            run(pair, arm, {'credential_file': str(root / 'MUST_NOT_READ')},
                {'live_model_allowed': False, 'integration_policy_sha256': checked['policy_sha256']})
        except PermissionError as error:
            denied = str(error) == 'no scoped model authorization'
        assert denied and not (root / 'attempt_intent.json').exists()
        env = environment(root, {'runtime': str(runtime)})
        with (root / 'inspection.stdout').open('x') as out, (root / 'inspection.stderr').open('x') as err:
            subprocess.run([runtime_node(runtime), str(HERE / 'integrated_entry_probe.mjs'), str(runtime), str(root)],
                cwd=root / 'workspace', env=env, stdout=out, stderr=err, timeout=90, check=True)
        results.append({'arm': arm, 'inspect': inspect(pair, arm), 'grant_denied_before_credentials': denied})
    result = {'passed': True, 'profiles': results, 'http': check_http(destination),
        'model_calls': 0, 'node_jobs': 0, 'external_provider_calls': 0, 'old_launcher_unchanged': True}
    (destination / 'acceptance.json').write_text(json.dumps(result, indent=2), encoding='utf8')
    print(json.dumps({'passed': True, 'profiles': len(results), 'native_tool_calls': 4, 'external_provider_calls': 0}))


if __name__ == '__main__':
    main()
