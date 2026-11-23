"""Explicit v1 integration; frozen launch_attempt.py and its defaults stay intact.

inspect is offline. run still requires the original scoped grant plus a binding
to the new integration policy. Loading a private launcher module keeps the HTTP
adapter local to this invocation, without mutating imported legacy callers.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from model_budget_errors import serve

HERE = Path(__file__).resolve().parent
POLICY = {'schema': 'c3-integrated-entry-v1', 'http_boundary': 'model_budget_errors',
    'shell_policy': 'shell-failure-propagation', 'runtime_interface': 'public-runtime-v1',
    'same_infrastructure_both_arms': True, 'automatic_retry': False, 'automatic_delivery': False}


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inspect(pair, arm):
    pair = Path(pair).resolve()
    if arm not in ('general', 'professional'):
        raise ValueError('Unknown arm')
    policy = pair / 'integration-policy.json'
    if json.loads(policy.read_bytes()) != POLICY:
        raise ValueError('Unsupported or changed integration policy')
    manifest = json.loads((pair / 'manifest.json').read_bytes())
    pins = manifest['source_sha256']
    root = pair / arm
    required = [Path(__file__).resolve(), HERE / 'launch_attempt.py', HERE / 'model_budget.py',
        HERE / 'model_budget_errors.py', HERE / 'native_attempt.mjs',
        HERE / 'integrated_dev/shell-failure-propagation.mjs', policy,
        root / 'dump.yml', root / 'prompt.txt', root / 'workspace/common/client.py',
        root / 'workspace/common/contract_client.py', root / 'workspace/common/runtime_info.py',
        root / 'workspace/common/runtime-binding.json',
        root / 'workspace/runtime/RUNTIME.json', root / 'workspace/runtime/RUNTIME.md']
    if any(str(file) not in pins for file in required):
        raise ValueError('Integration input is not frozen')
    for name, expected in pins.items():
        if digest(name) != expected:
            raise ValueError('Frozen integration source changed: ' + Path(name).name)
    from runtime_config import Loader
    import yaml
    rows = yaml.load((root / 'dump.yml').read_text(encoding='utf8'), Loader=Loader)
    plugins = [row for row in rows if row.get('id') == 'shell-failure-propagation']
    expected_plugin = (HERE / 'integrated_dev/shell-failure-propagation.mjs').as_uri()
    if len(plugins) != 1 or plugins[0].get('name') != expected_plugin or plugins[0].get('disabled', False):
        raise ValueError('Strict shell policy is not enabled exactly once')
    runtime_binding = json.loads((root / 'workspace/common/runtime-binding.json').read_bytes())
    if digest(root / 'workspace/runtime/RUNTIME.json') != runtime_binding['sha256']:
        raise ValueError('Public runtime identity mismatch')
    return {'passed': True, 'arm': arm, 'policy_sha256': digest(policy),
        'manifest_sha256': digest(pair / 'manifest.json'), 'checked_files': len(pins),
        'model_calls': 0, 'node_jobs': 0}


def load_launcher():
    spec = importlib.util.spec_from_file_location('_c3_explicit_integrated_launcher', HERE / 'launch_attempt.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.serve = serve
    return module


def environment(root, binding):
    from prepare_system_comparison import common_environment
    env = common_environment(root)
    env.update(C3_PYTHON=sys.executable, C3_MODULE_PATH=str(HERE),
        C3_RUNTIME=str(Path(binding['runtime']).resolve()))
    return env


def run(pair, arm, binding, grant):
    checked = inspect(pair, arm)
    if grant.get('integration_policy_sha256') != checked['policy_sha256']:
        raise PermissionError('Grant does not bind the integrated policy')
    launcher = load_launcher()
    launcher.common_environment = lambda root: environment(root, binding)
    return launcher.run(Path(pair), arm, binding, grant)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['inspect', 'run'])
    parser.add_argument('--pair', type=Path, required=True)
    parser.add_argument('--arm', choices=['general', 'professional'], required=True)
    parser.add_argument('--binding', type=Path)
    parser.add_argument('--authorization', type=Path)
    args = parser.parse_args()
    if args.action == 'inspect':
        print(json.dumps(inspect(args.pair, args.arm)))
    else:
        if args.binding is None or args.authorization is None:
            parser.error('run requires binding and authorization')
        code = run(args.pair, args.arm, json.loads(args.binding.read_bytes()), json.loads(args.authorization.read_bytes()))
        print(code)
        sys.exit(0 if code == 0 else 1)
