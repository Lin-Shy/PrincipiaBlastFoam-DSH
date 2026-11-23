"""Resume SSH transfers, then verify every tar member against the source manifest."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import tarfile
import time
import zstandard

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--backup', type=Path, required=True)
parser.add_argument('--host', required=True)
args = parser.parse_args()
backup = args.backup.resolve()
plan = json.loads((backup / 'plan.json').read_text())
remote = plan['work']
options = ['-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'ClearAllForwardings=yes', '-o', 'ConnectTimeout=15']
state = {'phase': 'waiting', 'groups': [], 'started': time.time()}


def save():
    temp = backup / 'transfer-status.tmp'
    temp.write_text(json.dumps(state, indent=2), encoding='utf8')
    temp.replace(backup / 'transfer-status.json')


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024**2), b''):
            result.update(block)
    return result.hexdigest()


def transfer(filename):
    destination = backup / filename
    batch = backup / 'sftp-batch.txt'
    batch.write_text('get -a ' + json.dumps(remote + '/' + filename) + ' ' + json.dumps(destination.as_posix()) + '\n', encoding='utf8')
    for attempt in range(8):
        with (backup / 'sftp.log').open('a', encoding='utf8') as log:
            result = subprocess.run(['sftp', '-b', str(batch), *options, args.host], stdout=log, stderr=log, timeout=14400)
        if result.returncode == 0:
            return destination
        state.update(phase='transfer-retry', attempt=attempt + 1)
        save()
        time.sleep(min(10 * (attempt + 1), 45))
    raise RuntimeError('Resumable transfer failed: ' + filename)


def transfer_archive(filename, expected_bytes):
    """Use four independent bounded SSH streams to tolerate per-connection latency."""
    destination = backup / filename
    pieces = backup / (filename + '.parts')
    pieces.mkdir(exist_ok=True)
    chunk = 128 * 1024**2
    # Reuse bytes already received by the older sequential SFTP worker.
    if destination.exists() and destination.stat().st_size == expected_bytes:
        return destination
    seed = pieces / 'seed'
    if destination.exists() and not seed.exists():
        destination.replace(seed)
    if seed.exists():
        with seed.open('rb') as source:
            for number, offset in enumerate(range(0, seed.stat().st_size, chunk)):
                part = pieces / ('part-%05d' % number)
                data = source.read(chunk)
                if not part.exists():
                    part.write_bytes(data)

    def download(number):
        offset = number * chunk
        size = min(chunk, expected_bytes - offset)
        part = pieces / ('part-%05d' % number)
        for attempt in range(8):
            received = part.stat().st_size if part.exists() else 0
            assert received <= size
            if received == size:
                return
            command = 'dd if=' + shlex.quote(remote + '/' + filename) + ' bs=1048576 iflag=skip_bytes,count_bytes skip=' + str(offset + received) + ' count=' + str(size - received) + ' status=none'
            try:
                with part.open('ab') as out, (pieces / ('error-%05d.log' % number)).open('ab') as err:
                    result = subprocess.run(['ssh', *options, args.host, command], stdout=out, stderr=err, timeout=900)
                if result.returncode == 0 and part.stat().st_size == size:
                    return
            except subprocess.TimeoutExpired:
                pass
            time.sleep(min(5 * (attempt + 1), 30))
        raise RuntimeError('Bounded range transfer failed: ' + str(number))

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(download, range((expected_bytes + chunk - 1) // chunk)))
    with destination.open('wb') as out:
        for number in range((expected_bytes + chunk - 1) // chunk):
            with (pieces / ('part-%05d' % number)).open('rb') as source:
                for block in iter(lambda: source.read(4 * 1024**2), b''):
                    out.write(block)
    assert destination.stat().st_size == expected_bytes
    return destination


def verify(name, expected):
    archive = backup / (name + '.tar.zst')
    manifest_path = backup / (name + '.manifest.json')
    assert digest(archive) == expected['archive_sha256'], 'Compressed archive hash mismatch'
    assert digest(manifest_path) == expected['manifest_sha256'], 'Manifest hash mismatch'
    manifest = json.loads(manifest_path.read_text(encoding='utf8'))
    entries = {row['path']: row for row in manifest['entries'] if row['type'] != 'special'}
    seen = set()
    verified_hashes = {}
    byte_count = 0
    with archive.open('rb') as compressed:
        with zstandard.ZstdDecompressor().stream_reader(compressed) as stream:
            with tarfile.open(fileobj=stream, mode='r|') as bundle:
                for member in bundle:
                    row = entries[member.name]
                    assert member.name not in seen, 'Duplicate archive path'
                    seen.add(member.name)
                    if member.isdir():
                        assert row['type'] == 'directory'
                    elif member.issym():
                        assert row['type'] == 'symlink' and member.linkname == row['target']
                    elif member.islnk():
                        assert row['type'] == 'file'
                        assert verified_hashes[member.linkname] == row['sha256']
                        verified_hashes[member.name] = row['sha256']
                    elif member.isfile():
                        assert row['type'] == 'file' and member.size == row['size']
                        result = hashlib.sha256()
                        source = bundle.extractfile(member)
                        for block in iter(lambda: source.read(4 * 1024**2), b''):
                            result.update(block)
                            byte_count += len(block)
                        assert result.hexdigest() == row['sha256'], 'Member hash mismatch: ' + member.name
                        verified_hashes[member.name] = result.hexdigest()
                    else:
                        raise ValueError('Unexpected archive member type')
                    if len(seen) % 1000 == 0:
                        state.update(verified_members=len(seen), verified_bytes=byte_count)
                        save()
    assert seen == set(entries), 'Missing archive members'
    receipt = {**expected, 'verified': True, 'verified_members': len(seen),
               'verified_content_bytes': byte_count, 'roots': manifest['roots'],
               'archive_local_path': str(archive), 'verified_at': time.time()}
    (backup / (name + '.verified.json')).write_text(json.dumps(receipt, indent=2), encoding='utf8')
    return receipt


try:
    completed = set()
    for group in plan['groups']:
        existing = backup / (group['name'] + '.verified.json')
        if existing.exists():
            receipt = json.loads(existing.read_text(encoding='utf8'))
            assert receipt['verified']
            assert digest(backup / (group['name'] + '.tar.zst')) == receipt['archive_sha256']
            state['groups'].append(receipt)
            completed.add(group['name'])
    errors = 0
    while len(completed) < len(plan['groups']):
        result = subprocess.run(['ssh', *options, args.host, 'cat ' + shlex.quote(remote + '/status.json')],
                                capture_output=True, text=True, encoding='utf8', timeout=45)
        if result.returncode:
            errors += 1
            state.update(phase='status-retry', errors=errors)
            save()
            if errors >= 12:
                raise RuntimeError('Remote archive status unreachable')
            time.sleep(15)
            continue
        status = json.loads(result.stdout)
        (backup / 'remote-status.json').write_text(json.dumps(status, indent=2), encoding='utf8')
        if status['phase'] == 'failed':
            raise RuntimeError('Remote archiving failed: ' + str(status.get('error')))
        ready = [row for row in status['groups'] if row['name'] not in completed]
        for expected in ready:
            name = expected['name']
            state.update(phase='transfer', current_group=name, expected_bytes=expected['archive_bytes'])
            save()
            print(json.dumps({'phase': 'transfer', 'group': name, 'bytes': expected['archive_bytes']}), flush=True)
            transfer(name + '.manifest.json')
            transfer_archive(name + '.tar.zst', expected['archive_bytes'])
            state.update(phase='verify')
            save()
            receipt = verify(name, expected)
            state['groups'].append(receipt)
            completed.add(name)
            print(json.dumps({'phase': 'verified', 'group': name, 'members': receipt['verified_members']}), flush=True)
        state.update(phase='waiting' if len(completed) < len(plan['groups']) else 'complete')
        save()
        if len(completed) < len(plan['groups']):
            time.sleep(15)
    state.update(phase='complete', finished=time.time())
    save()
    (backup / 'verification.json').write_text(json.dumps(state, indent=2), encoding='utf8')
except BaseException as error:
    state.update(phase='failed', error=repr(error))
    save()
    raise
