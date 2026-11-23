"""Prepare fresh integrated profiles for offline interface acceptance, not a run grant."""
import json
from pathlib import Path
import shutil
import sys
import zipfile
from start import HERE, WS
from runtime_config import prepare
from launch_integrated_attempt import POLICY, digest, inspect


def write(path, value):
    with path.open('x', encoding='utf8') as out:
        json.dump(value, out, ensure_ascii=False, indent=2)


def main():
    destination = Path(sys.argv[1]).resolve()
    base = WS / 'graduation-experiment-results/chapter3_end_to_end_evaluation/dsh'
    if not destination.is_relative_to(base) or destination.exists():
        raise ValueError('Fresh Chapter 3 archive directory required')
    data = WS / 'graduation-datasets/chapter03_simulation_tasks/couette_start_20261122'
    current = json.loads((data / 'CURRENT.json').read_bytes())
    release = data / current['release']
    if digest(release) != current['release_sha256']:
        raise ValueError('Release changed')
    archive = data / current['public_archive']
    if digest(archive) != current['public_sha256']:
        raise ValueError('Public task changed')
    runtime_packet = base / 'host_recovery_offline_20261122/runtime-interface'
    packet_manifest = json.loads((runtime_packet / 'manifest.json').read_bytes())
    if set(packet_manifest['files_sha256']) != {'RUNTIME.json', 'RUNTIME.md', 'runtime_info.py'}:
        raise ValueError('Unexpected public runtime files')
    for name, expected in packet_manifest['files_sha256'].items():
        if digest(runtime_packet / 'public' / name) != expected:
            raise ValueError('Public runtime packet changed')
    destination.mkdir(parents=True)
    results = []
    runtime = WS / '.chapter3-runtime/stage-20261117/dsh'
    for arm in ('general', 'professional'):
        pair = destination / 'pairs' / arm
        root = pair / arm
        old = base / 'startup_couette_pair100_20261122' / arm / arm
        for folder in ('workspace/common', 'workspace/runtime', 'workspace/case', 'workspace/delivery',
                       'home', 'tmp', 'user', 'cache', 'agents_home'):
            (root / folder).mkdir(parents=True)
        shutil.copytree(old / 'skills', root / 'skills')
        with zipfile.ZipFile(archive) as package:
            if set(package.namelist()) != {'TASK.md', 'settings.json'}:
                raise ValueError('Unexpected task members')
            for name in package.namelist():
                (root / 'workspace' / name).write_bytes(package.read(name))
        for name in ('RUNTIME.json', 'RUNTIME.md'):
            shutil.copyfile(runtime_packet / 'public' / name, root / 'workspace/runtime' / name)
        for source, target in [(HERE / 'startup_couette/runtime_client.py', 'client.py'),
            (HERE / 'cavity_agent/contract_client.py', 'contract_client.py'),
            (runtime_packet / 'public/runtime_info.py', 'runtime_info.py')]:
            shutil.copyfile(source, root / 'workspace/common' / target)
        write(root / 'workspace/common/runtime-binding.json', {'sha256': packet_manifest['files_sha256']['RUNTIME.json']})
        profile = (old / 'dump.yml').read_text(encoding='utf8').replace(str(old), str(root))
        profile += '\n- id: shell-failure-propagation\n  name: ' + (HERE / 'shell-failure-propagation.mjs').as_uri() + '\n'
        (root / 'dump.yml').write_text(profile, encoding='utf8')
        (root / 'prompt.txt').write_text(
            '先读取runtime/RUNTIME.md并执行python common/client.py runtime了解公开运行时身份。'
            '再按TASK.md/settings.json完成任务；submit和collect入口不变。'
            '本版本前台shell非零退出标为工具失败，不自动重试。禁止本地求解。'
            '仅使用本工作区公开资料；模型/节点预算必须由独立新协议授予。', encoding='utf8')
        write(pair / 'integration-policy.json', POLICY)
        pins = [Path(__file__).resolve(), HERE.parent / 'launch_integrated_attempt.py', HERE.parent / 'launch_attempt.py',
            HERE.parent / 'model_budget.py', HERE.parent / 'model_budget_errors.py', HERE.parent / 'native_attempt.mjs',
            HERE / 'shell-failure-propagation.mjs', HERE / 'startup_couette/runtime_client.py',
            pair / 'integration-policy.json', root / 'dump.yml', root / 'prompt.txt', release, archive,
            *[file for file in (root / 'workspace').rglob('*') if file.is_file()],
            *[file for file in (root / 'skills').rglob('*') if file.is_file()]]
        write(pair / 'manifest.json', {'source_sha256': {str(file): digest(file) for file in pins}})
        # Explicit denial makes inspection artifacts safe to hand off as a whole.
        write(pair / 'authorization.json', {'live_model_allowed': False,
            'reason': 'Offline integration acceptance only; no model or node grant'})
        prepare(root, runtime)
        results.append(inspect(pair, arm))
    shared = []
    for file in (destination / 'pairs/general/general/workspace').rglob('*'):
        if file.is_file():
            relative = file.relative_to(destination / 'pairs/general/general/workspace')
            other = destination / 'pairs/professional/professional/workspace' / relative
            if digest(file) != digest(other):
                raise ValueError('Public bytes differ between arms')
            shared.append(str(relative))
    write(destination / 'preparation.json', {'mode': 'offline interface acceptance',
        'task_fixture': current['task_id'], 'not_a_new_engineering_score': True,
        'new_model_authorization': False, 'model_calls': 0, 'node_jobs': 0,
        'shared_public_files': shared, 'profiles': results,
        'design_sha256': digest(WS / 'graduation-thesis-materials/graduation-research/chapters/chapter03.md')})
    print(json.dumps({'prepared': True, 'profiles': results, 'shared_public_files': len(shared)}))


if __name__ == '__main__':
    main()
