"""Prepare a NEW public-only identity packet from independently frozen evidence.

Does not patch an existing release, call a model, SSH, or run any solver.
"""
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys
import tarfile
import zipfile

HERE = Path(__file__).resolve().parent
WS = HERE.parents[4]
BASE = WS / 'graduation-experiment-results/chapter3_end_to_end_evaluation/dsh'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(destination):
    previous = BASE / 'startup_couette_pair100_20261122'
    candidate = previous / 'runtime_contract_candidate.json'
    binding = json.loads((previous / 'runtime_contract_candidate_binding.json').read_bytes())
    pipeline = BASE / 'openfoam_cavity_solve_20261122_r2/payload/run_case.sh'
    archive = previous / 'professional/operator/collected.tar'
    if digest(candidate) != binding['candidate_sha256'] or digest(pipeline) != binding['pipeline_sha256'] or digest(archive) != binding['source_archive_sha256']:
        raise ValueError('Frozen runtime evidence identity changed')
    contract = json.loads(candidate.read_bytes())
    if contract['solver_sha256'] != binding['solver_sha256']:
        raise ValueError('Solver binding mismatch')
    observed = {}
    with tarfile.open(archive) as package:
        for name, expected in [('bin/icoFoam', binding['solver_sha256']), ('payload/run_case.sh', binding['pipeline_sha256'])]:
            members = [row for row in package.getmembers() if row.isfile() and row.name.removeprefix('./') == name]
            if len(members) != 1 or hashlib.sha256(package.extractfile(members[0]).read()).hexdigest() != expected:
                raise ValueError('Archived executable/pipeline binding mismatch: ' + name)
        for command in contract['fixed_pipeline']:
            members = [row for row in package.getmembers() if row.isfile() and row.name.removeprefix('./') == 'logs/' + command + '.log']
            if len(members) != 1:
                raise ValueError('Expected exactly one native log for ' + command)
            raw = package.extractfile(members[0]).read(10000).decode('utf8')
            version = re.search(r'Version:\s*(\S+)', raw)
            build = re.search(r'Build\s*:\s*(\S+)', raw)
            if not version or not build or version[1] != contract['version'] or build[1] != contract['build']:
                raise ValueError('Native version mismatch: ' + command)
            observed[command] = {'version': version[1], 'build': build[1]}
    destination = Path(destination).resolve()
    destination.mkdir(parents=True, exist_ok=False)
    public = destination / 'public'
    public.mkdir()
    shutil.copyfile(candidate, public / 'RUNTIME.json')
    shutil.copyfile(HERE / 'runtime_info.py', public / 'runtime_info.py')
    guide = '''# 公开运行时身份

RUNTIME.json给出OpenFOAM发行版、版本、构建、固定四命令、登记限制及两种文件身份。
执行前读取；在新派发清单指定的SHA256下可运行：

python runtime_info.py --expected-sha256 {digest}

该身份依据2026-11-22已归档节点日志和固定流水线，不是对当前远端部署的实时证明。
操作者必须在新协议中绑定实际部署与本身份；两臂取得同一字节数据包。
当前包未派发，不修改任何旧题包、评分或协议。新题面需显式引用本文件。
本接口不校验/补写工程字典，不自动提交、不重试、不生成交件，也不运行求解。
任务输出格式要求仅在对应题面采用时适用；物理条件与容差由公开题面给出。
'''.format(digest=digest(candidate))
    (public / 'RUNTIME.md').write_text(guide, encoding='utf8')
    files = {file.name: digest(file) for file in public.iterdir()}
    with zipfile.ZipFile(destination / 'public-runtime.zip', 'x', compression=zipfile.ZIP_DEFLATED) as package:
        for name in sorted(files):
            package.write(public / name, name)
    manifest = {'status': 'prepared only; new protocol and dispatch binding required',
        'files_sha256': files, 'public_zip_sha256': digest(destination / 'public-runtime.zip'),
        'observed_versions': observed, 'evidence': {'candidate_sha256': digest(candidate),
            'pipeline_sha256': digest(pipeline), 'source_archive_sha256': digest(archive)},
        'live_remote_identity_checked': False, 'default_changed': False, 'model_calls': 0, 'node_jobs': 0}
    (destination / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf8')
    print(json.dumps(manifest))


if __name__ == '__main__':
    prepare(sys.argv[1])
