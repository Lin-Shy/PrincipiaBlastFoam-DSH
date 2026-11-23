"""Retire explicit source roots only after verified archival and a fresh source audit."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--plan', type=Path, required=True)
parser.add_argument('--receipts', type=Path, required=True)
parser.add_argument('--controller', type=Path, required=True)
parser.add_argument('--apply', action='store_true')
args = parser.parse_args()
controller = args.controller.resolve(strict=True)
plan = json.loads(args.plan.read_text())
work = Path(plan['work']).resolve(strict=True)
assert work.is_relative_to(controller)
receipts = json.loads(args.receipts.read_text())
assert receipts['phase'] == 'complete'
verified = {row['name']: row for row in receipts['groups']}
status = json.loads((work / 'status.json').read_text())
assert status['phase'] == 'complete'
remote = {row['name']: row for row in status['groups']}
library = json.loads((controller / 'case-library/index.json').read_text())
for case in library['cases']:
    for item in case['copied']:
        path = controller / 'case-library' / case['directory'] / item['path']
        assert hashlib.sha256(path.read_bytes()).hexdigest() == item['sha256']
protected = [controller, Path('/data/miniconda3'), Path('/data/conda-envs/hermes-agent'), Path('/data/conda-envs/deepseek-harness-build')]


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024**2), b''):
            result.update(block)
    return result.hexdigest()


def active_users(root):
    found = []
    for process in Path('/proc').glob('[0-9]*'):
        links = [process / 'exe', process / 'cwd']
        try:
            links.extend((process / 'fd').iterdir())
        except (FileNotFoundError, PermissionError):
            pass
        for link in links:
            try:
                target = Path(os.readlink(link).removesuffix(' (deleted)'))
                if target.is_absolute() and (target == root or target.is_relative_to(root)):
                    found.append({'pid': process.name, 'reference': str(link), 'target': str(target)})
            except (OSError, ValueError):
                pass
    return found


report = {'started': time.time(), 'apply': args.apply, 'roots': [],
          'before': {p: shutil.disk_usage(p)._asdict() for p in ('/', '/data')}}
for group in plan['groups']:
    name = group['name']
    receipt = verified[name]
    assert receipt['verified'] is True
    for key in ('archive_sha256', 'manifest_sha256', 'archive_bytes', 'entries'):
        assert receipt[key] == remote[name][key]
    manifest_path = work / (name + '.manifest.json')
    assert digest(manifest_path) == receipt['manifest_sha256']
    manifest = json.loads(manifest_path.read_text())
    assert manifest['roots'] == group['roots'] == receipt['roots']
    for value in group['roots']:
        root = Path(value)
        assert root.is_absolute() and root.resolve() == root
        assert len(root.parts) >= 3
        assert not any(root == p or root.is_relative_to(p) or p.is_relative_to(root) for p in protected)
        result = {'path': value, 'state': 'auditing'}
        report['roots'].append(result)
        if not root.exists():
            result['state'] = 'already-absent'
            continue
        # Existing desktop settings remain available to the live maintenance connection.
        if value in ('/root/.config', '/root/.bash_history', '/home/agent/.bash_history'):
            result['state'] = 'retained-active-settings'
            continue
        active = active_users(root)
        if active:
            result.update(state='retained-active-process', active=active)
            continue
        expected = {r['path']: r for r in manifest['entries'] if r['path'] == value.lstrip('/') or r['path'].startswith(value.lstrip('/') + '/')}
        actual = {root.as_posix().lstrip('/')}
        for current, dirs, files in os.walk(root, followlinks=False):
            actual.update((Path(current) / item).as_posix().lstrip('/') for item in dirs + files)
        changes = []
        if actual != set(expected):
            changes.append({'new': sorted(actual - set(expected))[:20], 'missing': sorted(set(expected) - actual)[:20]})
        for name, row in expected.items():
            path = Path('/' + name)
            try:
                info = path.lstat()
                valid = ((row['type'] == 'file' and stat.S_ISREG(info.st_mode) and info.st_size == row['size'] and digest(path) == row['sha256'])
                         or (row['type'] == 'directory' and stat.S_ISDIR(info.st_mode))
                         or (row['type'] == 'symlink' and stat.S_ISLNK(info.st_mode) and os.readlink(path) == row['target'])
                         or (row['type'] == 'special' and info.st_mode == row['stat_mode']))
                if not valid:
                    changes.append(name)
            except FileNotFoundError:
                changes.append(name)
        if changes:
            result.update(state='retained-changed-source', changes=changes[:50])
        else:
            result['state'] = 'eligible'
        print(json.dumps(result), flush=True)
        (work / 'cleanup-report.json').write_text(json.dumps(report, indent=2))
# Complete all source audits before the first destructive action.
if args.apply:
    for result in report['roots']:
        if result['state'] == 'eligible':
            root = Path(result['path'])
            assert not active_users(root), 'Source became active; stop cleanup'
            if root.is_dir():
                shutil.rmtree(root)
            else:
                root.unlink()
            result['state'] = 'deleted'
            (work / 'cleanup-report.json').write_text(json.dumps(report, indent=2))
report.update(finished=time.time(), after={p: shutil.disk_usage(p)._asdict() for p in ('/', '/data')})
(work / 'cleanup-report.json').write_text(json.dumps(report, indent=2))
print(json.dumps({'finished': True, 'apply': args.apply, 'roots': len(report['roots'])}), flush=True)
