"""Verify a completed archival transfer with one scoped scheduler maintenance job."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--work', type=Path, required=True)
parser.add_argument('--ssh-config', type=Path, required=True)
parser.add_argument('--hpc-root', required=True)
args = parser.parse_args()
work = args.work.resolve(strict=True)
status = json.loads((work / 'status.json').read_text())
assert status['phase'] == 'complete'
names = [item['name'] for item in status['groups']]
assert set(names) == {'historical-cases', 'research-records', 'old-environments', 'supplementary-records'}
root = args.hpc_root
assert root.startswith('/XYFS02/HDD_POOL/sysu_pww/sysu_pww_2/dsh-simulation/inputs/')
ssh = ['/usr/bin/ssh', '-F', str(args.ssh_config.resolve(strict=True)), 'starlight-c']
for name in names:
    record = json.loads((work / (name + '.hpc-transfer.json')).read_text())
    assert record['phase'] == 'transferred-awaiting-compute-node-verification'
subprocess.run(['/usr/bin/scp', '-F', str(args.ssh_config), str(work / 'verify_archive_batch.sh'),
                'starlight-c:' + root + '/tools/'], check=True, timeout=90)
job_name = 'maint-archive-20261122'
command = ['yhbatch', '--no-requeue', '--export=NONE', '-N', '1', '-n', '1', '-p', 'debug',
           '--time', '10', '--mem', '1024', '--job-name', job_name, '--chdir', root,
           '--output', root + '/logs/verify-%j.out', '--error', root + '/logs/verify-%j.err',
           root + '/tools/verify_archive_batch.sh', *names]
intent = {'purpose': 'Archive integrity maintenance only; no simulation or model inference',
          'submit_argv': command, 'groups': names, 'created_at': time.time()}
with (work / 'verification-submit-intent.json').open('x') as out:
    json.dump(intent, out, indent=2)
# An ambiguous submission is never retried automatically.
result = subprocess.run(ssh + [shlex.join(command)], capture_output=True, text=True, timeout=90)
(work / 'verification-submit.stdout').write_text(result.stdout)
(work / 'verification-submit.stderr').write_text(result.stderr)
result.check_returncode()
match = re.search(r'Submitted batch job\s+(\d+)', result.stdout)
assert match, 'Unknown submit outcome: reconcile the existing intent, never resubmit blindly'
job = match[1]
(work / 'verification-job.json').write_text(json.dumps({'job_id': job, **intent}, indent=2))
print(json.dumps({'phase': 'verification-job-submitted', 'job_id': job}), flush=True)
for attempt in range(180):
    received = []
    for name in names:
        response = subprocess.run(ssh + ['cat ' + shlex.quote(root + '/logs/' + name + '.verified.json')],
                                  capture_output=True, text=True, timeout=90)
        if response.returncode:
            break
        receipt = json.loads(response.stdout)
        sealed = json.loads((work / (name + '.sealed.json')).read_text())
        assert receipt['verified'] is True and receipt['verification_job_id'] == job
        assert all(receipt[key] == sealed[key] for key in ('archive_sha256', 'manifest_sha256', 'cipher_sha256', 'cipher_bytes'))
        received.append(receipt)
    if len(received) == len(names):
        password_hash = hashlib.sha256((work / 'archive-decryption.password').read_bytes()).hexdigest()
        catalog = {'phase': 'complete', 'groups': received, 'verification_job_id': job,
                   'recovery_password_sha256': password_hash, 'finished': time.time(),
                   'primary_destination': root, 'storage_policy': 'HPC bulk archives; Windows metadata and recovery material'}
        (work / 'archive-verification.json').write_text(json.dumps(catalog, indent=2))
        print(json.dumps({'phase': 'complete', 'job_id': job, 'groups': len(received)}), flush=True)
        break
    query = subprocess.run(ssh + ['scontrol show job -o ' + job], capture_output=True, text=True, timeout=90)
    if query.returncode == 0 and any('JobState=' + state in query.stdout for state in ('FAILED', 'CANCELLED', 'TIMEOUT', 'NODE_FAIL', 'OUT_OF_MEMORY')):
        raise RuntimeError('Archive verification job failed; preserve all research sources: ' + query.stdout)
    time.sleep(10)
else:
    raise TimeoutError('No complete verification receipt; preserve all research sources')
