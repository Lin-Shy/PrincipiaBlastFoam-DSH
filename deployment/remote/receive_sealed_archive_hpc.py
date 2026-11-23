"""Lightweight login-node file transfer. Checksums run separately via yhbatch."""
import argparse
import json
from pathlib import Path
import subprocess
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--root', type=Path, required=True)
parser.add_argument('--receipt', type=Path, required=True)
parser.add_argument('--source-host', required=True)
parser.add_argument('--source-port', type=int, required=True)
args = parser.parse_args()
root = args.root.resolve(strict=True)
receipt = json.loads(args.receipt.read_text())
name = receipt['name']
assert name.replace('-', '').isalnum()
target = root / 'archives' / receipt['cipher_file']
assert target.parent == root / 'archives' and target.resolve() == target
partial = target.with_suffix(target.suffix + '.partial')
identity = root / 'tmp/archive-transfer-key'
identity.chmod(0o600)
options = ['/usr/bin/ssh', '-F', '/dev/null', '-p', str(args.source_port), '-i', str(identity), '-o', 'IdentitiesOnly=yes', '-o', 'ProxyCommand=none',
           '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'ClearAllForwardings=yes',
           '-o', 'UserKnownHostsFile=' + str(root / 'tmp/source-known-hosts'), '-o', 'ConnectTimeout=45',
           '-o', 'ServerAliveInterval=30', '-o', 'ServerAliveCountMax=3', 'root@' + args.source_host]
if target.exists():
    assert target.stat().st_size == receipt['cipher_bytes']
    print(json.dumps({'phase': 'already-transferred', 'name': name}), flush=True)
    raise SystemExit(0)
for attempt in range(12):
    offset = partial.stat().st_size if partial.exists() else 0
    assert offset <= receipt['cipher_bytes']
    if offset == receipt['cipher_bytes']:
        break
    with partial.open('ab') as out, (root / 'logs' / (name + '.ssh.log')).open('ab') as err:
        process = subprocess.Popen(options + ['read-sealed ' + name + ' ' + str(offset)], stdout=out, stderr=err)
        started = time.monotonic()
        while process.poll() is None:
            time.sleep(5)
            size = partial.stat().st_size
            print(json.dumps({'phase': 'transfer', 'name': name, 'bytes': size,
                              'total': receipt['cipher_bytes'], 'bytes_per_second': (size - offset) / max(1, time.monotonic() - started)}), flush=True)
    if process.returncode == 0 and partial.stat().st_size == receipt['cipher_bytes']:
        break
    time.sleep(min(5 * (attempt + 1), 30))
assert partial.stat().st_size == receipt['cipher_bytes'], 'Incomplete transfer; source remains preserved'
partial.replace(target)
target.chmod(0o600)
result = {**receipt, 'phase': 'transferred-awaiting-compute-node-verification', 'hpc_archive_path': str(target)}
(root / 'logs' / (name + '.transfer.json')).write_text(json.dumps(result, indent=2))
print(json.dumps(result), flush=True)
