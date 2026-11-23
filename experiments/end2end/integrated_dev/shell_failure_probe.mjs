import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {randomUUID} from 'node:crypto';
import {pathToFileURL} from 'node:url';
import {failedForeground} from './shell-failure-propagation.mjs';

const [runtime, root, variant] = process.argv.slice(2);
const load = p => import(pathToFileURL(path.join(runtime, p)).href);
const {boot, loadLayeredEnv} = await load('packages/boot/app-boot/lib/index.js');
const {DSH_LAUNCH_ENVIRONMENT_KEY: key} = await load('packages/util/launch-environment/lib/index.js');
const ctx = await boot('c3-shell-failure-probe', path.join(root, 'boot.yml'),
  ['headless-startup', 'headless-runner'].map(id => ({id, disabled: true})),
  c => c.provide(key, loadLayeredEnv('c3-shell-failure-probe')),
  pathToFileURL(path.join(runtime, 'apps/cli/package.json')).href);
try {
  const observed = new Map(), calls = [];
  ctx.on('tools/result', (exec, result) => observed.set(exec.callId, result));
  const cases = [
    {id: 'success', command: "Add-Content calls.txt success; Write-Output 'stdout-ok'; exit 0", failed: false},
    {id: 'stderr_warning', command: "Add-Content calls.txt stderr_warning; [Console]::Error.WriteLine('warning-only'); exit 0", failed: false},
    {id: 'nonzero', command: "Add-Content calls.txt nonzero; Write-Output 'stdout-failed'; [Console]::Error.WriteLine('stderr-failed'); exit 7", failed: true},
    {id: 'native_child', command: "Add-Content calls.txt native_child; cmd.exe /d /c exit 9", failed: true},
    {id: 'native_explicit', command: "Add-Content calls.txt native_explicit; cmd.exe /d /c exit 9; exit $LASTEXITCODE", failed: true},
  ];
  for (const test of cases) {
    const callId = randomUUID();
    const result = await ctx.get('tools').execute({name: 'pwsh', arguments: {
      command: test.command, description: 'Controlled offline exit propagation: ' + test.id},
      callId, signal: new AbortController().signal});
    calls.push({id: test.id, command: test.command, result});
    // Save actual observations before assertions, including a failed probe.
    fs.writeFileSync('shell-failure-probe.json', JSON.stringify({variant, model_calls: 0, node_jobs: 0, calls}, null, 2));
    assert.deepEqual(observed.get(callId), result);
    assert.equal(result.isError, variant === 'on' && test.failed);
    const original = result.isError ? JSON.parse(result.content[0].text.split('\n')[1]).originalValue : result.value;
    assert.equal(original.kind, 'foreground');
    const expectedExit = {nonzero: 7, native_child: 1, native_explicit: 9};
    assert.equal(original.exitCode, expectedExit[test.id] ?? 0);
    if (test.id === 'nonzero') {
      assert(original.stdout.text.includes('stdout-failed'));
      assert(original.stderr.text.includes('stderr-failed'));
    }
  }
  assert.deepEqual(fs.readFileSync('calls.txt', 'utf8').trim().split(/\r?\n/), cases.map(x => x.id));
  // Pure classification only: never reproduce host OOM or terminate a real process.
  const exec = {name: 'pwsh'};
  for (const value of [{kind: 'foreground', exitCode: 3221226505},
    {kind: 'foreground', exitCode: null, timedOut: true},
    {kind: 'foreground', exitCode: null, aborted: true}]) {
    assert(failedForeground(exec, {isError: false, value}));
  }
  assert(!failedForeground(exec, {isError: false, value: {kind: 'background', exitCode: 7}}));
  assert(!failedForeground(exec, {isError: true, value: {kind: 'foreground', exitCode: 7}}));
  fs.writeFileSync('passed.json', JSON.stringify({passed: true, real_calls: calls.length,
    exact_once_markers: true, observer_matches: true, synthetic_edge_cases: 5}, null, 2), {flag: 'wx'});
} finally {
  await ctx.fiber.dispose();
}
