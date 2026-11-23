"""Hash one encrypted archive only inside a genuine allocated compute node."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--root', type=Path, required=True)
parser.add_argument('--name', required=True)
args = parser.parse_args()
job = os.environ.get('SLURM_JOB_ID', '')
assert job.isdigit(), 'Scheduler allocation required'
record = subprocess.check_output(['scontrol', 'show', 'job', '-o', job], text=True)
fields = dict(re.findall(r'(?:^| )([A-Za-z]+)=([^ ]+)', record))
assert fields['JobState'] == 'RUNNING'
assert fields['NodeList'] == os.environ.get('SLURM_JOB_NODELIST')
assert int(re.search(r'\((\d+)\)', fields['UserId'])[1]) == os.getuid()
hosts = subprocess.check_output(['scontrol', 'show', 'hostnames', fields['NodeList']], text=True).splitlines()
assert socket.gethostname().split('.')[0] in [item.split('.')[0] for item in hosts]
root = args.root.resolve(strict=True)
receipt = json.loads((root / 'logs' / (args.name + '.transfer.json')).read_text())
archive = Path(receipt['hpc_archive_path'])
assert archive.parent == root / 'archives' and archive.resolve() == archive
result = hashlib.sha256()
with archive.open('rb') as stream:
    for block in iter(lambda: stream.read(4 * 1024**2), b''):
        result.update(block)
assert archive.stat().st_size == receipt['cipher_bytes']
assert result.hexdigest() == receipt['cipher_sha256']
assert receipt['source_members_verified'] is True
receipt.update(verified=True, verified_at=time.time(), verification_job_id=job,
               verification_host=socket.gethostname(), verification_scope='Source tar members verified on owned Linux; sealed bytes SHA256 verified on allocated HPC compute node')
output = root / 'logs' / (args.name + '.verified.json')
with output.open('x') as out:
    json.dump(receipt, out, indent=2)
print(json.dumps(receipt), flush=True)
