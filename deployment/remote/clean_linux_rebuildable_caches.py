"""Clean explicit rebuildable caches after verified archival, preserving live runtimes."""
import argparse
import json
import os
from pathlib import Path
import shutil
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--work', type=Path, required=True)
parser.add_argument('--apply', action='store_true')
args = parser.parse_args()
work = args.work.resolve(strict=True)
receipts = json.loads((work / 'archive-verification.json').read_text())
assert receipts['phase'] == 'complete'
assert {item['name'] for item in receipts['groups']} == {item['name'] for item in json.loads((work / 'status.json').read_text())['groups']}
assert all(item['verified'] for item in receipts['groups'])
cleanup = json.loads((work / 'cleanup-report.json').read_text())
assert cleanup['apply'] is True and 'finished' in cleanup
report = {'apply': args.apply, 'started': time.time(), 'actions': [],
          'before': {p: shutil.disk_usage(p)._asdict() for p in ('/', '/data')}}
targets = [Path(p) for p in (
    '/root/.cache/pip', '/root/.npm/_cacache', '/root/.cache/pnpm',
    '/root/.cache/node', '/root/.cache/node-gyp', '/root/.cache/ms-playwright',
    '/data/pip-cache', '/data/cache', '/var/cache/dnf', '/data/conda-pkgs/cache')]
initial_library = work.parent.parent / 'case-library-initial'
if initial_library.is_dir():
    assert initial_library.resolve() == initial_library
    assert json.loads((initial_library / 'index.json').read_text())['schema'] == 'retained-case-configs-v1'
    targets.append(initial_library)
# Conda expanded packages may supply live environment symlinks; remove only download archives.
targets.extend(p for p in Path('/data/conda-pkgs').iterdir() if p.is_file() and (p.name.endswith('.conda') or p.name.endswith('.tar.bz2')))
versions = Path('/root/.vscode-server/cli/servers')
if versions.is_dir():
    targets.extend(p for p in versions.iterdir() if p.name.startswith('Stable-') and p.is_dir())
references = []
for process in Path('/proc').glob('[0-9]*'):
    paths = [process / 'exe', process / 'cwd']
    try:
        paths.extend((process / 'fd').iterdir())
    except OSError:
        pass
    for path in paths:
        try:
            references.append(os.readlink(path).removesuffix(' (deleted)'))
        except OSError:
            pass
active_code = {Path(item).name.removeprefix('code-') for item in references if '/root/.vscode-server/code-' in item}
for path in targets:
    if not path.exists():
        continue
    assert path.is_absolute() and path.resolve() == path and len(path.parts) >= 3
    assert not path.is_symlink()
    active = any(item == str(path) or item.startswith(str(path) + '/') for item in references)
    if path.parent == versions and path.name.removeprefix('Stable-') in active_code:
        active = True
    row = {'path': str(path), 'state': 'retained-active' if active else 'eligible'}
    if args.apply and not active:
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        row['state'] = 'deleted'
    report['actions'].append(row)
    (work / 'cache-cleanup-report.json').write_text(json.dumps(report, indent=2))
# Archive blobs are staging copies; the complete verified primary archives remain authoritative.
for receipt in receipts['groups']:
    for filename, size in ((receipt['name'] + '.tar.zst', receipt['archive_bytes']),
                           (receipt['cipher_file'], receipt['cipher_bytes'])):
        blob = work / filename
        assert blob.parent == work and blob.resolve() == blob
        if blob.exists():
            assert blob.stat().st_size == size and not blob.is_symlink()
            row = {'path': str(blob), 'state': 'eligible-verified-staging-copy'}
            if args.apply:
                blob.unlink()
                row['state'] = 'deleted'
            report['actions'].append(row)
report.update(finished=time.time(), after={p: shutil.disk_usage(p)._asdict() for p in ('/', '/data')})
(work / 'cache-cleanup-report.json').write_text(json.dumps(report, indent=2))
print(json.dumps(report, indent=2))
