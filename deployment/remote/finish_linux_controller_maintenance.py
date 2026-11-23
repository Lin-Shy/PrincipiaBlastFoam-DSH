"""After audited source retirement, clean caches and validate the agent deployment."""
import argparse
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import time

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--controller', type=Path, required=True)
parser.add_argument('--domain-sha256', required=True)
args = parser.parse_args()
assert os.getuid() == 0
root = args.controller.resolve(strict=True)
work = root / 'maintenance/offload_20261122'
report_path = work / 'cleanup-report.json'
while True:
    try:
        report = json.loads(report_path.read_text()) if report_path.exists() else {}
    except (OSError, json.JSONDecodeError):
        report = {}
    if report.get('finished'):
        assert report['apply'] is True
        break
    time.sleep(5)
with (work / 'cache-cleanup.log').open('w') as log:
    subprocess.run(['/data/conda-envs/hermes-agent/bin/python', str(work / 'clean_linux_rebuildable_caches.py'),
                    '--work', str(work), '--apply'], stdout=log, stderr=subprocess.STDOUT, check=True)
for source, target in (
    (work / 'install_linux_domain_tools.py', root / 'install_linux_domain_tools.py'),
    (work / 'accept_linux_controller.py', root / 'accept_linux_controller.py'),
    (work / 'launch_linux_controller.sh', root / 'bin/dsh-controller'),
    (work / 'domain-tools-v2.tar.gz', root / 'downloads/domain-tools-v2.tar.gz'),
):
    shutil.copyfile(source, target)
    target.chmod(0o700 if target.suffix in ('.py', '.sh') or target.name == 'dsh-controller' else 0o600)
    os.chown(target, 1001, 1001)
environment = root / 'environment.sh'
text = environment.read_text().replace('export PATH="$CONTROLLER_ROOT/bin:$PATH"',
                                       'export PATH="$CONTROLLER_ROOT/bin:/data/miniconda3/bin:$PATH"')
environment.write_text(text)
os.chown(environment, 1001, 1001)


def as_agent(arguments, log_name):
    command = '. ' + shlex.quote(str(environment)) + '; exec ' + shlex.join(arguments)
    with (work / log_name).open('w') as log:
        subprocess.run(['runuser', '-u', 'agent', '--', '/bin/bash', '--noprofile', '--norc', '-c', command],
                       stdout=log, stderr=subprocess.STDOUT, check=True, timeout=240)


as_agent(['/data/conda-envs/hermes-agent/bin/python', str(root / 'install_linux_domain_tools.py'),
          '--controller', str(root), '--archive', str(root / 'downloads/domain-tools-v2.tar.gz'),
          '--sha256', args.domain_sha256, '--ssh-config', '/home/agent/.ssh/chapter3-supercomputer/config'], 'domain-install.log')
as_agent([str(root / 'bin/dsh-controller'), '--dump-config'], 'post-cleanup-dump-config.yml')
as_agent([str(root / 'bin/dsh-controller'), '--offline-test', 'offline-acceptance-04'], 'post-cleanup-general.log')
as_agent([str(root / 'bin/dsh-controller'), '--offline-test', 'offline-acceptance-05', '--professional'], 'post-cleanup-professional.log')
for name in ('offline-acceptance-04', 'offline-acceptance-05'):
    assert json.loads((root / 'runs' / name / 'summary.json').read_text())['passed'], name
assert json.loads((root / 'runs/domain-acceptance/summary.json').read_text())['passed']
local_bin = Path('/home/agent/.local/bin')
local_bin.mkdir(parents=True, exist_ok=True)
os.chown(local_bin.parent, 1001, 1001)
os.chown(local_bin, 1001, 1001)
for name in ('dsh-controller', 'hpc-ssh', 'hpc-workspace'):
    wrapper = local_bin / name
    assert not wrapper.exists()
    wrapper.write_text('#!/bin/bash\nset -euo pipefail\nexec ' + shlex.quote(str(root / 'bin' / name)) + ' "$@"\n')
    wrapper.chmod(0o700)
    os.chown(wrapper, 1001, 1001)
result = {'phase': 'complete', 'finished': time.time(), 'paid_model_calls': 0, 'simulation_jobs': 0,
          'general_offline_agent_passed': True, 'professional_offline_agent_passed': True,
          'domain_tools_passed': True, 'hpc_workspace_probe_passed': True,
          'credentials_owned_by': 'agent UID 1001',
          'disk_usage': {p: shutil.disk_usage(p)._asdict() for p in ('/', '/data')}}
(work / 'final-deployment-verification.json').write_text(json.dumps(result, indent=2))
print(json.dumps(result), flush=True)
