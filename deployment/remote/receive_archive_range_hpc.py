"""Receive one bounded byte range on a login node; do no bulk hashing there."""
import argparse
import json
from pathlib import Path
import sys

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--root', type=Path, required=True)
parser.add_argument('--name', required=True)
parser.add_argument('--offset', type=int, required=True)
parser.add_argument('--size', type=int, required=True)
args = parser.parse_args()
root = args.root.resolve(strict=True)
assert args.name.replace('-', '').isalnum()
receipt = json.loads((root / 'logs' / (args.name + '.sealed.json')).read_text())
target = root / 'archives' / (receipt['cipher_file'] + '.partial')
assert target.parent == root / 'archives' and target.resolve() == target and not target.is_symlink()
assert target.stat().st_size == receipt['cipher_bytes']
assert 0 <= args.offset < receipt['cipher_bytes'] and 0 < args.size <= receipt['cipher_bytes'] - args.offset
received = 0
with target.open('r+b') as out:
    out.seek(args.offset)
    while block := sys.stdin.buffer.read(min(4 * 1024**2, args.size - received)):
        out.write(block)
        received += len(block)
        if received == args.size:
            break
assert received == args.size and not sys.stdin.buffer.read(1), 'Incomplete or oversized stream'
marker = root / 'logs' / ('%s.range-%012d.json' % (args.name, args.offset))
marker.write_text(json.dumps({'offset': args.offset, 'size': received}))
print(json.dumps({'offset': args.offset, 'size': received}), flush=True)
