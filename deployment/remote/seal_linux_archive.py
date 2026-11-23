"""Verify every archive member, then seal with standard OpenSSL AES-256-CBC.

Keep the encrypted-file SHA256 in the trusted Windows catalog and check it
before decrypting. A random 256-bit password file stays outside the archive.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--work', type=Path, required=True)
parser.add_argument('--name', required=True)
parser.add_argument('--password-file', type=Path, required=True)
parser.add_argument('--zstd', type=Path, required=True)
parser.add_argument('--openssl', type=Path, required=True)
args = parser.parse_args()
work = args.work.resolve(strict=True)
status = json.loads((work / 'status.json').read_text())
expected = next(item for item in status['groups'] if item['name'] == args.name)
assert args.name.replace('-', '').isalnum()


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024**2), b''):
            result.update(block)
    return result.hexdigest()


archive = work / (args.name + '.tar.zst')
manifest_path = work / (args.name + '.manifest.json')
assert digest(archive) == expected['archive_sha256']
assert digest(manifest_path) == expected['manifest_sha256']
manifest = json.loads(manifest_path.read_text())
rows = {row['path']: row for row in manifest['entries'] if row['type'] != 'special'}
seen = set()
hashes = {}
decompressor = subprocess.Popen([str(args.zstd), '-dc', str(archive)], stdout=subprocess.PIPE)
try:
    with tarfile.open(fileobj=decompressor.stdout, mode='r|') as bundle:
        for member in bundle:
            row = rows[member.name]
            assert member.name not in seen
            seen.add(member.name)
            if member.isdir():
                assert row['type'] == 'directory'
            elif member.issym():
                assert row['type'] == 'symlink' and member.linkname == row['target']
            elif member.islnk():
                assert row['type'] == 'file' and hashes[member.linkname] == row['sha256']
                hashes[member.name] = row['sha256']
            elif member.isfile():
                assert row['type'] == 'file' and row['size'] == member.size
                result = hashlib.sha256()
                source = bundle.extractfile(member)
                for block in iter(lambda: source.read(4 * 1024**2), b''):
                    result.update(block)
                assert result.hexdigest() == row['sha256'], member.name
                hashes[member.name] = result.hexdigest()
            else:
                raise ValueError('Unexpected member type')
    # Consume the trailing tar padding before waiting for the decompressor.
    while decompressor.stdout.read(4 * 1024**2):
        pass
    assert decompressor.wait() == 0
finally:
    if decompressor.poll() is None:
        decompressor.kill()
assert seen == set(rows)
output = work / (args.name + '.tar.zst.aes256')
assert not output.exists()
assert shutil.disk_usage(work).free > archive.stat().st_size + 1024**3
subprocess.run([str(args.openssl), 'enc', '-aes-256-cbc', '-salt', '-pbkdf2', '-iter', '200000', '-md', 'sha256',
                '-pass', 'file:' + str(args.password_file.resolve(strict=True)), '-in', str(archive), '-out', str(output)], check=True)
output.chmod(0o600)
receipt = {**expected, 'source_members_verified': True, 'verified_members': len(seen),
           'roots': manifest['roots'], 'cipher_file': output.name, 'cipher_bytes': output.stat().st_size,
           'cipher_sha256': digest(output), 'sealed_at': time.time(),
           'encryption': 'openssl enc aes-256-cbc PBKDF2 SHA256 iterations=200000; verify trusted ciphertext SHA256 before decrypting'}
(work / (args.name + '.sealed.json')).write_text(json.dumps(receipt, indent=2))
print(json.dumps(receipt), flush=True)
