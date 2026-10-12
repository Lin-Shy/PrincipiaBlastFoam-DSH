"""等待代理续跑屏障后执行原评分重放与分供应商费用审计，零在线调用。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--amendment', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if os.environ.get('PYTHONHASHSEED') != '0':
        raise ValueError('Frozen PYTHONHASHSEED=0 required')
    root, amendment = args.root.resolve(), args.amendment.resolve()
    sys.path.insert(0, str(root / 'runtime'))
    from chapter2_formal_runtime import verify
    protocol, protocol_sha = verify(root, require_snapshot=False)
    source = Path(__file__).resolve().parent
    scripts = {'scores': source / 'chapter2_formal_analysis.py', 'costs': source / 'chapter2_provider_costs.py'}
    sha = lambda file: hashlib.sha256(file.read_bytes()).hexdigest()
    bindings = {key: sha(file) for key, file in scripts.items()}
    args.output.mkdir(parents=True, exist_ok=False)
    summary = {'schema': 'proxy-zero-model-postprocess-v1', 'protocol_sha256': protocol_sha,
               'script_sha256': sha(Path(__file__)), 'analysis_sha256': bindings, 'new_llm_calls': 0,
               'completed': {}, 'real_human48': 'pending; no AI substitution'}
    (args.output / 'launch.json').write_text(json.dumps(summary, indent=2) + '\n')
    while True:
        complete = root / 'completion'
        scores_ready = all((complete / (stage + '--' + str(shard) + '.json')).exists()
                           for stage in ['review', 'adjudication'] for shard in range(protocol['scoring_shards']))
        for stage, ready in [('scores', scores_ready), ('costs', (complete / 'controller.json').exists())]:
            if stage in summary['completed'] or not ready:
                continue
            if any(sha(file) != bindings[key] for key, file in scripts.items()):
                raise ValueError('Derived script drift; use a new version')
            output = args.output / (stage + '_001.json')
            command = [sys.executable, str(scripts[stage])]
            if stage == 'scores':
                command += ['scores']
            else:
                command += ['--amendment', str(amendment)]
            command += ['--root', str(root), '--output', str(output)]
            with (args.output / (stage + '.log')).open('x') as log:
                result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
            if result.returncode:
                raise RuntimeError(stage + ' failed; retained log')
            summary['completed'][stage] = {'path': str(output), 'sha256': sha(output)}
            (args.output / 'progress.json').write_text(json.dumps(summary, indent=2) + '\n')
            print('POSTPROCESS', stage, 'complete', flush=True)
        if len(summary['completed']) == 2:
            summary['status'] = 'machine_postprocessing_complete_real_human_pending'
            (args.output / 'completion.json').write_text(json.dumps(summary, indent=2) + '\n')
            return
        print('WAIT proxy continuation review/adjudication/controller barriers', flush=True)
        time.sleep(30)


if __name__ == '__main__':
    main()
