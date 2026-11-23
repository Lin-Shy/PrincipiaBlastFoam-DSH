"""Install hash-bound domain plugins and run deterministic Linux deployment checks."""
import argparse
import hashlib
import json
from pathlib import Path
import os
import shutil
import subprocess
import tarfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--controller', type=Path, required=True)
parser.add_argument('--archive', type=Path, required=True)
parser.add_argument('--sha256', required=True)
parser.add_argument('--ssh-config', type=Path, required=True)
args = parser.parse_args()
root = args.controller.resolve(strict=True)
assert hashlib.sha256(args.archive.read_bytes()).hexdigest() == args.sha256
app = root / 'application'
app.mkdir(mode=0o700)
with tarfile.open(args.archive) as bundle:
    for member in bundle.getmembers():
        assert (app / member.name).resolve().is_relative_to(app)
        assert member.isfile() or member.isdir()
    bundle.extractall(app, filter='data')
binding = {'archive_sha256': args.sha256, 'files': {str(p.relative_to(app)): hashlib.sha256(p.read_bytes()).hexdigest() for p in app.rglob('*') if p.is_file()}}
(app / 'SOURCE_BINDING.json').write_text(json.dumps(binding, indent=2))
cluster_config = app / 'cluster/config'
cluster_config.mkdir()
shutil.copyfile(args.ssh_config.resolve(strict=True), cluster_config / 'ssh_config')
(cluster_config / 'ssh_config').chmod(0o600)
environment = dict(os.environ, C3_RUNTIME=str(root / 'source'), C3_MODULE_PATH=str(app), C3_PYTHON=os.environ['npm_config_python'])
run = root / 'runs/domain-acceptance'
run.mkdir(mode=0o700)
(run / 'pressure.txt').write_text('0 100\n1 102\n2 100\n')
probe = run / 'verify.mjs'
probe.write_text('''import assert from 'node:assert/strict';
import fs from 'node:fs';
import {pathToFileURL} from 'node:url';
const tools = new Map();
for (const file of ['pressure-tool.mjs','measurement-audit.mjs']) {
  const plugin = await import(pathToFileURL(process.env.C3_MODULE_PATH+'/'+file));
  plugin.apply({tools:{register(tool){tools.set(tool.name,tool)}}});
}
const converted = JSON.parse((await tools.get('convert_volume_rates').execute({input:JSON.stringify({values:[1,-2],from:'L/s',to:'m3/s'})})).result);
assert.deepEqual(converted.values,[0.001,-0.002]);
const covered = JSON.parse((await tools.get('interval_coverage').execute({input:JSON.stringify({window:[0,5],intervals:[[0,2],[1,4],null]})})).result);
assert.equal(covered.covered,4); assert.equal(covered.uncovered,1);
const events = JSON.parse((await tools.get('latest_attempt_events').execute({input:JSON.stringify({job:'test',events:[{job:'test',attempt:1,event:'write',time:0},{job:'test',attempt:2,event:'write',time:1},{job:'test',attempt:2,event:'done',time:2}],writeEvent:'write',terminalEvents:['done']})})).result);
assert.equal(events.attempt,2); assert.equal(events.distinct,1); assert.equal(events.terminal,'done');
assert.equal((await tools.get('pressure_window').execute({input:'pressure.txt',output:'pressure.json',ambient:100,start:0,end:2})).status,'computed');
const observation=JSON.parse(fs.readFileSync('pressure.json','utf8'));
assert.equal(observation.metrics[0].peak_overpressure_pa,2);
assert.equal(observation.metrics[0].whole_window_positive_area_pa_s,2);
fs.writeFileSync('summary.json',JSON.stringify({passed:true,tools:[...tools.keys()],skills:3,paid_model_calls:0,node_jobs:0,scope:'deterministic domain plugin deployment; no scientific simulation'},null,2));
''')
subprocess.run([str(root / 'bin/node'), str(probe)], cwd=run, env=environment, check=True, timeout=90)
patch = [{'id': 'skill-filesystem', 'config': {'includeDefaultRoots': False, 'customSkillDirs': [str(app / 'skills')]}},
         {'insert': [
             {'id': 'engineering-time-series', 'name': (app / 'pressure-tool.mjs').as_uri()},
             {'id': 'measurement-audit', 'name': (app / 'measurement-audit.mjs').as_uri()}]}]
(app / 'professional.patch.json').write_text(json.dumps(patch, indent=2))
with (run / 'dump-config.yml').open('w') as out:
    subprocess.run([str(root / 'bin/node'), str(root / 'source/apps/cli/lib/bin.js'), '--profile', 'headless', '--patch', str(app / 'professional.patch.json'), '--dump-config'], cwd=run, env=environment, stdout=out, check=True, timeout=90)
print((run / 'summary.json').read_text())
with (run / 'hpc-probe.json').open('w') as out:
    subprocess.run([environment['C3_PYTHON'], str(app / 'cluster/scripts/hpc.py'), 'probe', '--workspace', 'xyfs02'], cwd=run, env=environment, stdout=out, check=True, timeout=90)
