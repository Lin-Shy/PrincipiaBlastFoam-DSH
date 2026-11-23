"""Release only a generated plaintext staging archive after an encrypted round trip.

Original research roots remain untouched. This permits sealing subsequent groups
on a small disk while the encrypted first group is still being transferred.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--work', type=Path, required=True)
parser.add_argument('--name', required=True)
parser.add_argument('--password-file', type=Path, required=True)
parser.add_argument('--openssl', type=Path, required=True)
args = parser.parse_args()
work = args.work.resolve(strict=True)
assert args.name.replace('-', '').isalnum()
receipt = json.loads((work / (args.name + '.sealed.json')).read_text())
assert receipt['source_members_verified']
assert all(Path(root).exists() for root in receipt['roots'])
cipher = work / receipt['cipher_file']
plain = work / (args.name + '.tar.zst')
assert cipher.parent == plain.parent == work
assert cipher.resolve() == cipher and plain.resolve() == plain
process = subprocess.Popen([str(args.openssl), 'enc', '-d', '-aes-256-cbc', '-pbkdf2', '-iter', '200000', '-md', 'sha256',
                            '-pass', 'file:' + str(args.password_file.resolve(strict=True)), '-in', str(cipher)], stdout=subprocess.PIPE)
result = hashlib.sha256()
for block in iter(lambda: process.stdout.read(4 * 1024**2), b''):
    result.update(block)
assert process.wait() == 0 and result.hexdigest() == receipt['archive_sha256']
assert plain.stat().st_size == receipt['archive_bytes'] and not plain.is_symlink()
plain.unlink()
audit = {'name': args.name, 'round_trip_verified': True, 'deleted_generated_staging_path': str(plain),
         'original_research_roots_preserved': receipt['roots'], 'finished': time.time()}
(work / (args.name + '.plain-staging-release.json')).write_text(json.dumps(audit, indent=2))
print(json.dumps(audit), flush=True)
