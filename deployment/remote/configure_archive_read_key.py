"""Add or revoke one temporary forced-command read key on the owned Linux host."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('action', choices=['add', 'revoke'])
parser.add_argument('--work', type=Path, required=True)
args = parser.parse_args()
assert os.getuid() == 0
work = args.work.resolve(strict=True)
public = (work / 'archive-transfer-key.pub').read_text().strip()
assert public.startswith('ssh-ed25519 ') and public.endswith('linux-offload-20261122-read-only')
command = '/data/conda-envs/hermes-agent/bin/python ' + shlex.quote(str(work / 'read_sealed_archive.py'))
assert '"' not in command and '\n' not in command
line = 'restrict,command="' + command + '" ' + public
keys = Path('/root/.ssh/authorized_keys')
assert keys.resolve() == keys and not keys.is_symlink()
original = keys.read_bytes()
if args.action == 'add':
    assert line.encode() not in original
    (work / 'authorized_keys.before').write_bytes(original)
    content = original + (b'\n' if original and not original.endswith(b'\n') else b'') + line.encode() + b'\n'
    for private in ('archive-decryption.password', 'authorized_keys.before'):
        (work / private).chmod(0o600)
else:
    lines = original.splitlines(keepends=True)
    removed = [item for item in lines if item.rstrip(b'\r\n') == line.encode()]
    assert len(removed) <= 1
    content = b''.join(item for item in lines if item.rstrip(b'\r\n') != line.encode())
temporary = keys.with_name('authorized_keys.offload.tmp')
with temporary.open('xb') as out:
    out.write(content)
temporary.chmod(0o600)
temporary.replace(keys)
print(json.dumps({'action': args.action, 'original_sha256': hashlib.sha256(original).hexdigest(),
                  'result_sha256': hashlib.sha256(content).hexdigest(),
                  'scope': 'Only reads sealed archives; shell, PTY and forwarding prohibited'}))
