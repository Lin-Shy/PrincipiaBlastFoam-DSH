"""Run only the four selected local signal-readout replacements. No cluster binding."""
import argparse
import hashlib
import shutil
import sys
import zipfile
from pathlib import Path

from cluster_first import RetryGate
from local_first_wave import (HERE, WS, base, batch, runtime, sha, write, read, files,
                              common_environment, launch_attempt, snapshot_runtime, runtime_digest, dispatch)

ORDER = (('B12', 'general'), ('B14', 'general'), ('B14', 'professional'), ('B20', 'general'))
OUT = batch / 'local_recheck_100'


def verify_inputs(short, arm):
    task = 'CH3-DEV-' + short
    old = batch / 'local_live' / task / arm
    source = batch / 'work' / arm / task / 'first' / 'input'
    row = next(v for v in read(dispatch / 'index.json') if v['id'] == task)
    package = dispatch / row['zip']
    pins = read(batch / 'local_live/version.json')
    if sha(package) != row['sha256'] or any(sha(Path(name)) != digest for name, digest in pins.items()):
        raise ValueError('public input or system version changed')
    with zipfile.ZipFile(package) as archive:
        expected = {p: hashlib.sha256(archive.read(p)).hexdigest() for p in archive.namelist() if not p.endswith('/')}
    if files(source) != expected:
        raise ValueError('unpacked input changed')
    return old, source, pins, row


def run_arm(short, arm):
    old, source, pins, row = verify_inputs(short, arm)
    pair = OUT / row['id']
    root = pair / arm
    if root.exists():
        if not (root/'sealed.json').exists() and not (root/'retry/sealed.json').exists():
            raise RuntimeError(f'existing incomplete attempt: {short} {arm}; reconcile before resuming')
        final = root/'retry' if (root/'retry/sealed.json').exists() else root
        receipt = read(final / 'sealed.json')
        if receipt['archive_sha256'] != sha(final / 'submission.zip'):
            raise RuntimeError('sealed submission mismatch')
        if receipt['stop_queue']:
            if final != root or (root/'retry').exists():
                raise RuntimeError('retry already used or in progress; queue stopped')
            from resume_readout import resume_unanswered
            code = resume_unanswered(root, short, arm, pins)
            seal_arm(root, root/'retry', short, arm, code)
        return
    binding = read(base / 'pilot_decision_20261117' / (arm + '.binding.json'))
    binding.pop('cluster', None)
    root.mkdir(parents=True, exist_ok=False)
    shutil.copytree(source, root / 'workspace')
    for folder in ('workspace/common', 'workspace/delivery', 'home', 'tmp', 'user', 'cache', 'agents_home'):
        (root / folder).mkdir()
    shutil.copytree(old / 'skills', root / 'skills')
    shutil.copyfile(old / 'prompt.txt', root / 'prompt.txt')
    config = (old / 'dump.yml').read_text(encoding='utf-8')
    (root / 'dump.yml').write_text(config.replace(str(old), str(root)), encoding='utf-8')
    protocol = {'task': row['id'], 'public_sha256': row['sha256'], 'source_sha256': pins, 'cluster_jobs': 0}
    if not (pair / 'manifest.json').exists():
        write(pair / 'manifest.json', protocol)
    if read(pair / 'manifest.json') != protocol:
        raise ValueError('pair manifest mismatch')
    grant = dict(live_model_allowed=True, arms=[arm], pair_manifest_sha256=sha(pair/'manifest.json'),
                 authorization_evidence='approved scoped local replacement: ' + row['id'] + '/' + arm,
                 isolation_accepted=True, isolation_evidence='separate workspace, sessions and outputs; shared host nonblind',
                 complete_task_required=False, budget_unit='requests', max_requests_per_arm=100,
                 max_output_tokens=8192, wall_seconds=14400, generation=binding['generation'],
                 **{k: binding[k] for k in ('model', 'context_window', 'endpoint_sha256')})
    print('START', short, arm, flush=True)
    code = launch_attempt.run(pair, arm, binding, grant)
    seal_arm(root, root, short, arm, code)


def seal_arm(root, destination, short, arm, code):
    events = read(destination/'provider_ledger/ledger.json')['events']
    delivery = root/'workspace/delivery'
    manifest = {}
    with zipfile.ZipFile(destination/'submission.zip', 'x', compression=zipfile.ZIP_DEFLATED) as archive:
        for file in sorted(delivery.rglob('*')):
            if file.is_symlink() or getattr(file.lstat(), 'st_file_attributes', 0) & 1024:
                raise ValueError('linked delivery')
            if file.is_file():
                name = file.relative_to(delivery).as_posix()
                manifest[name] = sha(file)
                archive.write(file, name)
    unknown = [event['request'] for event in events if event['state'] != 'settled']
    stop = not events or events[-1]['state'] != 'settled' or bool(code and len(events) < 100)
    write(destination/'sealed.json', dict(task='CH3-DEV-'+short, arm=arm, cap=100, requests=len(events),
          known_tokens=sum(event['usage']['total_tokens'] for event in events if event.get('usage')),
          unknown=unknown, files=manifest, archive_sha256=sha(destination/'submission.zip'), exit=code,
          cluster_jobs=0, money=None, stop_queue=stop))
    print('SEALED', short, arm, len(events), len(manifest), 'unsettled', len(unknown), flush=True)
    if stop:
        raise RuntimeError('operator attention required; no further requests')


def main(live):
    policy = read(batch/'authorization.json')
    scope = policy['local_replacements']
    if policy['requests_per_arm'] != 100 or scope['new_arms'] != [f'{short}/{arm}' for short, arm in ORDER] or scope['cluster_jobs'] != 0:
        raise PermissionError('current policy does not authorize this local queue')
    if (runtime.parent/'chapter3-model.lock').exists():
        raise RuntimeError('another Chapter 3 run is active')
    for short, arm in ORDER:
        verify_inputs(short, arm)
    if not live:
        print('4 verified local readout arms; 100 each; 0 cluster jobs')
        return
    launch_attempt.Gate = RetryGate
    snapshot_runtime.sha = runtime_digest
    launch_attempt.common_environment = lambda path: dict(common_environment(path), C3_PYTHON=sys.executable,
                                                         C3_MODULE_PATH=str(HERE.parent), C3_RUNTIME=str(runtime))
    for short, arm in ORDER:
        run_arm(short, arm)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', action='store_true')
    main(parser.parse_args().run)
