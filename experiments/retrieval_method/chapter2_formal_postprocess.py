"""正式阶段屏障后自动执行零模型派生审计；不启动或重启在线实验。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--human-output', type=Path, required=True)
    parser.add_argument('--timeout-seconds', type=int, default=7200)
    args = parser.parse_args()
    if os.environ.get('PYTHONHASHSEED') != '0':
        raise ValueError('冻结PYTHONHASHSEED=0必需')
    root = args.root.resolve()
    sys.path.insert(0, str(root / 'runtime'))
    from chapter2_formal_runtime import verify, ANSWER_ARMS
    protocol, protocol_sha = verify(root, require_snapshot=False)
    source = Path(__file__).resolve().parent
    analysis = source / 'chapter2_formal_analysis.py'
    human = source / 'chapter2_human_review.py'
    args.output.mkdir(parents=True, exist_ok=False)
    summary = {'schema': 'formal-zero-model-postprocess-v1', 'protocol_sha256': protocol_sha,
               'script_sha256': sha(Path(__file__)), 'analysis_sha256': sha(analysis),
               'human_export_sha256': sha(human), 'online_llm_calls': 0, 'completed': {},
               'limitations': 'machine audits only; true human48ratings required separately; no online resume or tuning'}
    (args.output / 'launch.json').write_text(json.dumps(summary, indent=2)+'\n')
    started = time.monotonic()

    def run(name, command, artifact):
        # 操作前复核所绑定的脚本，不能随运行中编辑漂移。
        if sha(analysis) != summary['analysis_sha256'] or sha(human) != summary['human_export_sha256']:
            raise ValueError('派生脚本运行中漂移，请使用新版本')
        with (args.output / (name+'.log')).open('x') as log:
            result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
        if result.returncode:
            raise RuntimeError(name+' failed; inspect preserved log')
        summary['completed'][name] = {'artifact': str(artifact.resolve()), 'sha256': sha(artifact)}
        (args.output / 'progress.json').write_text(json.dumps(summary, indent=2)+'\n')
        print('POSTPROCESS', name, 'complete', flush=True)

    def derive(stage):
        artifact = args.output / (stage+'_001.json')
        run(stage, [sys.executable, str(analysis), stage, '--root', str(root), '--output', str(artifact)], artifact)

    while time.monotonic()-started < args.timeout_seconds:
        complete = root / 'completion'
        if 'answers' not in summary['completed'] and all((complete / ('answer--'+arm+'.json')).exists() for arm in ANSWER_ARMS):
            derive('answers')
        if 'human_export' not in summary['completed'] and (complete / 'review_prepare.json').exists():
            run('human_export', [sys.executable, str(human), 'export', '--root', str(root), '--output', str(args.human_output)], args.human_output / 'manifest.json')
        if 'scores' not in summary['completed'] and all((complete / (stage+'--'+str(shard)+'.json')).exists() for stage in ['review','adjudication'] for shard in range(protocol['scoring_shards'])):
            derive('scores')
        if 'costs' not in summary['completed'] and (complete / 'controller.json').exists():
            derive('costs')
        if len(summary['completed']) == 4:
            summary['status'] = 'machine_postprocessing_complete_human_judgments_pending'
            (args.output / 'completion.json').write_text(json.dumps(summary, indent=2)+'\n')
            return
        print('WAIT registered stage barriers; completed='+','.join(summary['completed']), flush=True)
        time.sleep(30)
    summary['status'] = 'deadline_reached_original_experiment_not_restarted'
    (args.output / 'timeout.json').write_text(json.dumps(summary, indent=2)+'\n')


if __name__ == '__main__':
    main()
