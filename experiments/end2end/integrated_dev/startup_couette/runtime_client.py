"""Opt-in public runtime view plus unchanged registration/collection wire data."""
import json
from pathlib import Path
import sys
from contract_client import collect, submit
from runtime_info import inspect


def execute(root, action):
    root = Path(root)
    binding = json.loads((root / 'common/runtime-binding.json').read_bytes())
    runtime = inspect(root / 'runtime/RUNTIME.json', binding['sha256'])
    if action == 'runtime':
        return {'state': 'runtime_identity', 'runtime': runtime, 'sha256': binding['sha256'],
            'evidence_scope': 'archived runtime; actual deployment must be bound by the new operator protocol'}
    if action not in ('submit', 'collect'):
        raise ValueError('runtime, submit or collect required')
    result = {'submit': submit, 'collect': collect}[action](root)
    if 'required_delivery' in result:
        result['required_delivery']['other_files'].append('profile.csv')
    result['public_runtime_sha256'] = binding['sha256']
    return result


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('runtime, submit or collect')
    print(json.dumps(execute(Path(__file__).resolve().parent.parent, sys.argv[1]), ensure_ascii=False, indent=2))
