"""Resume a direct Linux-to-HPC SFTP upload using the authorized agent identity."""
import argparse
import json
from pathlib import Path
import shlex
import subprocess
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--work', type=Path, required=True)
parser.add_argument('--name', required=True)
parser.add_argument('--ssh-config', type=Path, required=True)
parser.add_argument('--hpc-root', required=True)
args = parser.parse_args()
work = args.work.resolve(strict=True)
receipt = json.loads((work / (args.name + '.sealed.json')).read_text())
assert receipt['name'] == args.name and args.name.replace('-', '').isalnum()
root = args.hpc_root
assert root.startswith('/XYFS02/HDD_POOL/sysu_pww/sysu_pww_2/dsh-simulation/inputs/')
source = work / receipt['cipher_file']
assert source.parent == work and source.resolve() == source
assert source.stat().st_size == receipt['cipher_bytes']
batch = work / (args.name + '.sftp.batch')
partial = root + '/archives/' + receipt['cipher_file'] + '.direct.partial'
initialize = 'test -e ' + shlex.quote(partial) + ' || (umask 077; set -C; : > ' + shlex.quote(partial) + ')'
subprocess.run(['/usr/bin/ssh', '-F', str(args.ssh_config), 'starlight-c', initialize], check=True, timeout=90)
batch.write_text('put -a ' + json.dumps(str(source)) + ' ' + json.dumps(partial) + '\n' +
                 'put ' + json.dumps(str(work / (args.name + '.sealed.json'))) + ' ' + json.dumps(root + '/logs/' + args.name + '.sealed.json') + '\n')
for attempt in range(8):
    process = subprocess.run(['/usr/bin/sftp', '-F', str(args.ssh_config.resolve(strict=True)), '-b', str(batch), 'starlight-c'])
    if process.returncode == 0:
        break
    time.sleep(min(5 * (attempt + 1), 30))
else:
    raise RuntimeError('Direct SFTP transfer failed; preserve originals')
code = ('import pathlib,json; r=pathlib.Path(' + repr(root) + '); n=' + repr(args.name) + '; '
        'v=json.loads((r/"logs"/(n+".sealed.json")).read_text()); '
        'p=r/"archives"/(v["cipher_file"]+".direct.partial"); t=r/"archives"/v["cipher_file"]; '
        'assert p.stat().st_size==v["cipher_bytes"]; '
        'assert not t.exists(); p.rename(t); t.chmod(0o600); '
        'v.update(phase="transferred-awaiting-compute-node-verification",hpc_archive_path=str(t)); '
        '(r/"logs"/(n+".transfer.json")).write_text(json.dumps(v,indent=2)); print(json.dumps(v))')
result = subprocess.run(['/usr/bin/ssh', '-F', str(args.ssh_config), 'starlight-c',
                         '/APP/u22/x86/anaconda3/202309/bin/python3 -I -c ' + shlex.quote(code)], check=True, capture_output=True, text=True, timeout=90)
(work / (args.name + '.hpc-transfer.json')).write_text(result.stdout)
print(result.stdout, flush=True)
