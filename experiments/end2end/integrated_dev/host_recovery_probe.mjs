// One harmless child process through a real, unmodified DSH tool registry.
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {randomUUID} from 'node:crypto';
import {pathToFileURL} from 'node:url';
const [runtime, root] = process.argv.slice(2);
const load = p => import(pathToFileURL(path.join(runtime, p)).href);
const {boot, loadLayeredEnv} = await load('packages/boot/app-boot/lib/index.js');
const {DSH_LAUNCH_ENVIRONMENT_KEY: key} = await load('packages/util/launch-environment/lib/index.js');
const started = Date.now();
const ctx = await boot('c3-host-recovery', path.join(root, 'boot.yml'),
  ['headless-startup', 'headless-runner'].map(id => ({id, disabled: true})),
  c => c.provide(key, loadLayeredEnv('c3-host-recovery')),
  pathToFileURL(path.join(runtime, 'apps/cli/package.json')).href);
try {
  fs.writeFileSync('child.py', "import json, os, time\ntime.sleep(2)\nprint(json.dumps({'child_ok': True, 'pid': os.getpid()}))\n", {flag: 'wx'});
  const result = await ctx.get('tools').execute({name: 'pwsh', arguments: {
    command: "& $env:C3_PYTHON -B child.py; exit $LASTEXITCODE",
    description: 'Offline host recovery: harmless Python child through native shell'},
    callId: randomUUID(), signal: new AbortController().signal});
  const passed = !result.isError && result.value?.exitCode === 0 &&
    !result.value.timedOut && !result.value.aborted && JSON.parse(result.value.stdout.text).child_ok === true;
  fs.writeFileSync('host-probe.json', JSON.stringify({passed, elapsed_ms: Date.now() - started,
    model_calls: 0, node_jobs: 0, command_count: 1, result}, null, 2), {flag: 'wx'});
  assert(passed);
} finally { await ctx.fiber.dispose(); }
