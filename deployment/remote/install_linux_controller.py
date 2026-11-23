"""Finish this isolated controller's verified upload; no model or scheduler."""
import base64
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import argparse
import shlex

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--root', type=Path, required=True)
parser.add_argument('--source-sha256', required=True)
parser.add_argument('--python', type=Path, required=True)
args = parser.parse_args()
root = args.root.resolve()
assert root.is_dir() and (root / 'bin/node').is_file()
assert not (root / 'source').exists()
assert shutil.disk_usage(root).free > 7 * 1024**3
downloads = root / 'downloads'
archive = downloads / 'controller-source.tar.gz'
assert hashlib.sha256(archive.read_bytes()).hexdigest() == args.source_sha256
pnpm = downloads / 'pnpm-11.7.0.tgz'
integrity = json.loads((downloads / 'pnpm-integrity.json').read_text())['integrity']
assert 'sha512-' + base64.b64encode(hashlib.sha512(pnpm.read_bytes()).digest()).decode() == integrity
for archive, destination in ((archive, root), (pnpm, root / 'pnpm')):
    with tarfile.open(archive) as bundle:
        for member in bundle.getmembers():
            assert (destination / member.name).resolve().is_relative_to(destination)
            assert not member.issym() and not member.islnk()
        bundle.extractall(destination, filter='data')
for folder in ('tmp', 'cache', 'store'):
    (root / folder).mkdir()
wrapper = root / 'bin/pnpm'
wrapper.write_text('#!/bin/bash\nset -euo pipefail\nROOT="$(cd "$(dirname "$0")/.." && pwd -P)"\nexec "$ROOT/bin/node" "$ROOT/pnpm/package/bin/pnpm.cjs" "$@"\n')
wrapper.chmod(0o700)
env = root / 'environment.sh'
env.write_text('export CONTROLLER_ROOT=' + shlex.quote(str(root)) + '\n'
               'export PATH="$CONTROLLER_ROOT/bin:$PATH"\n'
               'export HOME="$CONTROLLER_ROOT/home"\n'
               'export TMPDIR="$CONTROLLER_ROOT/tmp"\n'
               'export XDG_CACHE_HOME="$CONTROLLER_ROOT/cache"\n'
               'export npm_config_python=' + shlex.quote(str(args.python.resolve())) + '\n'
               'export DSH_HOME="$CONTROLLER_ROOT/dsh-home"\n'
               'export DSH_TELEMETRY_MODE=DISABLED\n'
               'export ENABLE_EXECUTION=false\nexport REQUIRE_EXECUTION=false\n')
print(json.dumps({'uploads_verified': True, 'source_extracted': True,
                  'available_gib': round(shutil.disk_usage(root).free / 1024**3, 2)}))
