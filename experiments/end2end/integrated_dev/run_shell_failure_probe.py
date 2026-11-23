"""Normal DSH registry probe in fresh profiles; no provider or scheduler calls."""
import json
from pathlib import Path
import subprocess
import sys
from start import HERE, WS, prepare, runtime_node, common_environment


def main():
    destination = Path(sys.argv[1]).resolve()
    runtime = WS / '.chapter3-runtime/stage-20261117/dsh'
    template = WS / 'graduation-experiment-results/chapter3_end_to_end_evaluation/dsh/openfoam_cavity_revision100_20261122/old/professional'
    for variant in ('off', 'on'):
        root = destination / variant
        for folder in ('workspace', 'home', 'agents_home', 'skills', 'user', 'tmp', 'cache'):
            (root / folder).mkdir(parents=True, exist_ok=False)
        config = (template / 'dump.yml').read_text(encoding='utf8').replace(str(template), str(root))
        if variant == 'on':
            config += '\n- id: shell-failure-propagation\n  name: ' + (HERE / 'shell-failure-propagation.mjs').as_uri() + '\n'
        (root / 'dump.yml').write_text(config, encoding='utf8')
        prepare(root, runtime)
        env = common_environment(root)
        env.update(C3_RUNTIME=str(runtime), C3_PYTHON=sys.executable, C3_MODULE_PATH=str(HERE.parent))
        with (root / 'stdout.log').open('x') as out, (root / 'stderr.log').open('x') as err:
            subprocess.run([runtime_node(runtime), str(HERE / 'shell_failure_probe.mjs'), str(runtime), str(root), variant],
                cwd=root / 'workspace', env=env, stdout=out, stderr=err, check=True, timeout=180)
        print(variant, json.loads((root / 'workspace/passed.json').read_bytes()), flush=True)


if __name__ == '__main__':
    main()
