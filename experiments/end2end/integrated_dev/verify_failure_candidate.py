"""Archive related tests and inspect the explicit candidate profile, offline."""
import json
from pathlib import Path
import subprocess
import sys
from start import HERE, WS, common_environment, runtime_node


def main():
    destination = Path(sys.argv[1]).resolve()
    output = destination / sys.argv[2]
    output.mkdir(exist_ok=False)
    project = HERE.parents[2]
    runtime = WS / '.chapter3-runtime/stage-20261117/dsh'
    root = destination / 'probe02/on'
    env = common_environment(root)
    env.update(C3_RUNTIME=str(runtime), C3_PYTHON=sys.executable, C3_MODULE_PATH=str(HERE.parent))
    profile = root / 'home/profiles' / sys.argv[2]
    profile.mkdir(parents=True, exist_ok=False)
    bundle = profile / 'node_modules/c3-inspection-bundle'
    bundle.mkdir(parents=True)
    (bundle / 'package.json').write_text(json.dumps({'name': 'c3-inspection-bundle',
        'dsh': {'bundle': {'patch': './cordis.patch.yml'}}}), encoding='utf8')
    rows = (root / 'boot.yml').read_text(encoding='utf8')
    (bundle / 'cordis.patch.yml').write_text('- insert:\n' + ''.join('    ' + line for line in rows.splitlines(keepends=True)), encoding='utf8')
    (profile / 'package.json').write_text(json.dumps({'name': 'error-inspection', 'private': True,
        'dsh': {'profile': {'bundles': ['c3-inspection-bundle']}}}), encoding='utf8')
    checks = [
        ('python', [sys.executable, '-B', '-m', 'pytest', 'experiments/end2end/test_model_budget_errors.py',
            'experiments/end2end/test_stage_runtime.py', '-q', '-o', 'addopts=',
            '--junitxml=' + str(output / 'pytest.xml')], project),
        ('bundle', ['npm.cmd', 'run', 'check'], project / 'packages/principia-dsh-bundle'),
        ('dump-config', [runtime_node(runtime), str(runtime / 'apps/cli/lib/bin.js'), '--profile',
            sys.argv[2], '--dump-config'], root / 'workspace'),
    ]
    results = []
    if '--dump-only' in sys.argv[3:]:
        checks = [check for check in checks if check[0] == 'dump-config']
    for name, command, cwd in checks:
        with (output / f'{name}.stdout.log').open('x', encoding='utf8') as out, (output / f'{name}.stderr.log').open('x', encoding='utf8') as err:
            result = subprocess.run(command, cwd=cwd, env=env, stdout=out, stderr=err, timeout=180)
        valid = result.returncode == 0
        if name == 'dump-config':
            dumped = (output / f'{name}.stdout.log').read_text(encoding='utf8')
            valid = valid and 'id: shell-failure-propagation' in dumped and 'id: tools' in dumped
            valid = valid and not (output / f'{name}.stderr.log').read_text(encoding='utf8').strip()
        results.append({'check': name, 'exit_code': result.returncode, 'passed': valid})
        print(name, result.returncode, flush=True)
    with (output / 'verification.json').open('x', encoding='utf8') as out:
        json.dump({'model_calls': 0, 'node_jobs': 0, 'checks': results}, out, indent=2)
    if not all(row['passed'] for row in results):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
