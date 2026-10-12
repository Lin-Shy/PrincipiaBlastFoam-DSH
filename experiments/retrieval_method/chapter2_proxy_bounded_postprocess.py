"""等待有缺失槽位的受限执行结束，再做独立重放/费用/供应商审计；零API。"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('root', 'amendment', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    if os.environ.get('PYTHONHASHSEED') != '0':
        raise ValueError('Frozen PYTHONHASHSEED=0 required')
    root, amendment = args.root.resolve(), args.amendment.resolve()
    sys.path.insert(0, str(root / 'runtime'))
    from chapter2_formal_runtime import verify
    protocol, protocol_sha = verify(root, require_snapshot=False)
    source = Path(__file__).resolve().parent
    scripts = {'scores': source / 'chapter2_formal_incomplete_score_analysis.py',
        'costs': source / 'chapter2_provider_costs.py',
        'providers': source / 'chapter2_scoring_provider_audit.py'}
    sha = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
    bindings = {name: sha(path) for name, path in scripts.items()}
    args.output.mkdir(parents=True, exist_ok=False)
    summary = {'schema': 'bounded-proxy-zero-api-postprocess-v1', 'protocol_sha256': protocol_sha,
        'script_sha256': sha(Path(__file__)), 'analysis_sha256': bindings,
        'execution_config_sha256': sha(amendment / 'execution_config.json'), 'new_llm_calls': 0,
        'completed': {}, 'real_human48': 'pending actual human input'}
    (args.output / 'launch.json').write_text(json.dumps(summary, indent=2) + '\n')
    finished = amendment / 'bounded_execution_finished.json'
    while True:
        ready = finished.exists()
        handles = []
        try:
            if ready:
                for name in ('controller.lock', 'parallel--review.lock', 'parallel--adjudication.lock'):
                    handle = (root / 'locks' / name).open('a')
                    handles.append(handle)
                    fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            ready = False
        finally:
            for handle in handles:
                handle.close()
        if ready:
            break
        print('WAIT bounded review/adjudication execution; no formal completion implied', flush=True)
        time.sleep(30)
    result = json.loads(finished.read_text())
    if result['protocol_sha256'] != protocol_sha or result['execution_amendment_sha256'] != summary['execution_config_sha256']:
        raise ValueError('Bounded execution result drift')
    summary['execution_status'] = result['status']
    for name, script in scripts.items():
        if any(sha(path) != bindings[key] for key, path in scripts.items()):
            raise ValueError('Analysis source drift; start a new postprocessor version')
        output = args.output / (name + '_001.json')
        command = [sys.executable, str(script)]
        if name == 'scores':
            command += ['scores', '--allow-incomplete']
        elif name == 'costs':
            command += ['--amendment', str(amendment)]
        else:
            command += ['--partial']
        command += ['--root', str(root), '--output', str(output)]
        with (args.output / (name + '.log')).open('x') as log:
            step = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
        if step.returncode:
            raise RuntimeError(name + ' failed; retained log, no model calls')
        summary['completed'][name] = {'path': str(output), 'sha256': sha(output)}
        (args.output / 'progress.json').write_text(json.dumps(summary, indent=2) + '\n')
        print('POSTPROCESS', name, 'complete', flush=True)
    summary['status'] = 'bounded_machine_audits_complete_human_pending'
    (args.output / 'completion.json').write_text(json.dumps(summary, indent=2) + '\n')


if __name__ == '__main__':
    main()
