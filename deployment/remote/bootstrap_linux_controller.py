"""Run with an existing Python 3.11 on the selected independent Linux host."""
import base64
import hashlib
import json
from pathlib import Path
import shutil
import tarfile
import urllib.request
import argparse

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--root', type=Path, required=True)
parser.add_argument('--node-source', type=Path, required=True)
args = parser.parse_args()
root = args.root.resolve()
if root.exists():
    raise RuntimeError('Refusing existing deployment directory')
assert root.parent.is_dir()
assert shutil.disk_usage(root.parent).free > 8 * 1024**3
root.mkdir(mode=0o700)
for folder in ('bin', 'downloads', 'logs', 'runs', 'home'):
    (root / folder).mkdir()
node = args.node_source.resolve()
shutil.copyfile(node, root / 'bin/node')
(root / 'bin/node').chmod(0o700)
metadata = json.loads(urllib.request.urlopen('https://registry.npmjs.org/pnpm/11.7.0', timeout=20).read())
raw = urllib.request.urlopen(metadata['dist']['tarball'], timeout=40).read()
algorithm, expected = metadata['dist']['integrity'].split('-', 1)
assert algorithm == 'sha512'
assert base64.b64encode(hashlib.sha512(raw).digest()).decode() == expected
archive = root / 'downloads/pnpm-11.7.0.tgz'
archive.write_bytes(raw)
with tarfile.open(archive) as bundle:
    for member in bundle.getmembers():
        target = (root / 'pnpm' / member.name).resolve()
        assert target.is_relative_to(root / 'pnpm')
        assert not member.issym() and not member.islnk()
    bundle.extractall(root / 'pnpm', filter='data')
(root / 'DEPLOYMENT.json').write_text(json.dumps({
    'model_calls': 0, 'node_jobs': 0,
    'node_sha256': hashlib.sha256((root / 'bin/node').read_bytes()).hexdigest(),
    'pnpm_version': '11.7.0', 'pnpm_sha512': expected,
    'research_data_deleted': False}, indent=2))
print(json.dumps({'root': str(root), 'remaining_gib': round(shutil.disk_usage(root).free / 1024**3, 2),
                  'bootstrap_ready': True}))
