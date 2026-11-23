"""Manifest and archive explicit inactive roots; never deletes source files."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tarfile
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--plan', type=Path, required=True)
parser.add_argument('--resume', action='store_true')
args = parser.parse_args()
plan = json.loads(args.plan.read_text())
work = Path(plan['work']).resolve()
work.mkdir(parents=True, exist_ok=args.resume, mode=0o700)
status = json.loads((work / 'status.json').read_text()) if args.resume else {'phase': 'starting', 'groups': [], 'started': time.time()}


def save():
    temporary = work / 'status.tmp'
    temporary.write_text(json.dumps(status, indent=2))
    temporary.replace(work / 'status.json')


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024**2), b''):
            result.update(block)
    return result.hexdigest()


try:
    for group in plan['groups']:
        name = group['name']
        assert name.replace('-', '').isalnum()
        completed = next((item for item in status['groups'] if item['name'] == name), None)
        if completed:
            assert digest(work / (name + '.manifest.json')) == completed['manifest_sha256']
            blob = work / (name + '.tar.zst')
            # An already verified staging blob may have been removed to free space.
            assert not blob.exists() or digest(blob) == completed['archive_sha256']
            continue
        roots = [Path(p) for p in group['roots']]
        assert all(p.is_absolute() and p.resolve() == p and (p.is_dir() or p.is_file()) for p in roots)
        assert all(not work.is_relative_to(p) for p in roots)
        status.update(phase='manifest', current_group=name, files=0, bytes=0)
        save()
        entries = []
        for root in roots:
            paths = [root]
            for current, dirs, files in os.walk(root, followlinks=False):
                paths.extend(Path(current) / n for n in sorted(dirs + files))
            for path in paths:
                before = path.lstat()
                row = {'path': path.as_posix().lstrip('/'), 'mode': stat.S_IMODE(before.st_mode),
                       'uid': before.st_uid, 'gid': before.st_gid, 'mtime_ns': before.st_mtime_ns}
                if stat.S_ISREG(before.st_mode):
                    row.update(type='file', size=before.st_size, sha256=digest(path))
                    after = path.stat()
                    assert (before.st_size, before.st_mtime_ns, before.st_ino) == (after.st_size, after.st_mtime_ns, after.st_ino)
                    status['bytes'] += before.st_size
                elif stat.S_ISDIR(before.st_mode):
                    row['type'] = 'directory'
                elif stat.S_ISLNK(before.st_mode):
                    row.update(type='symlink', target=os.readlink(path))
                else:
                    row.update(type='special', stat_mode=before.st_mode)
                entries.append(row)
                status['files'] += 1
                if len(entries) % 500 == 0:
                    save()
        manifest = {'schema': 'linux-offload-manifest-v1', 'name': name,
                    'roots': [str(p) for p in roots], 'entries': entries}
        (work / (name + '.manifest.json')).write_text(json.dumps(manifest, ensure_ascii=True, indent=2))
        status.update(phase='compress', archive_members=0)
        save()
        archive = work / (name + '.tar.zst')
        if args.resume and archive.exists():
            assert archive.parent == work and archive.is_file() and not archive.is_symlink()
            archive.unlink()
        with (work / (name + '.compression.log')).open('wb') as log:
            compressor = subprocess.Popen([plan['zstd'], '-T2', '-5', '--long=27', '-o', str(archive)],
                                          stdin=subprocess.PIPE, stdout=log, stderr=log)
            with tarfile.open(fileobj=compressor.stdin, mode='w|', format=tarfile.PAX_FORMAT, dereference=False) as bundle:
                for index, row in enumerate(entries):
                    if row['type'] == 'special':
                        continue
                    if index % 500 == 0:
                        assert shutil.disk_usage(work).free > 1024**3, 'Archive staging space reserve reached'
                        status['archive_members'] = index
                        save()
                    bundle.add('/' + row['path'], arcname=row['path'], recursive=False)
            compressor.stdin.close()
            assert compressor.wait() == 0, 'Compression failed'
        group_result = {'name': name, 'archive_bytes': archive.stat().st_size,
                        'archive_sha256': digest(archive),
                        'manifest_sha256': digest(work / (name + '.manifest.json')),
                        'entries': len(entries), 'regular_bytes': sum(r.get('size', 0) for r in entries)}
        status['groups'].append(group_result)
        status.update(phase='group-complete')
        save()
    status.update(phase='complete', finished=time.time())
    save()
except BaseException as error:
    status.update(phase='failed', error=repr(error))
    save()
    raise
