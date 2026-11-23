// Check the prepared composition, without model or scheduler dispatch.
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {randomUUID} from 'node:crypto';
import {pathToFileURL} from 'node:url';
const [runtime, root] = process.argv.slice(2);
const load = p => import(pathToFileURL(path.join(runtime, p)).href);
const {boot, loadLayeredEnv} = await load('packages/boot/app-boot/lib/index.js');
const {DSH_LAUNCH_ENVIRONMENT_KEY: key} = await load('packages/util/launch-environment/lib/index.js');
const ctx = await boot('c3-integrated-entry', path.join(root, 'boot.yml'),
  ['headless-startup', 'headless-runner'].map(id => ({id, disabled: true})),
  c => c.provide(key, loadLayeredEnv('c3-integrated-entry')),
  pathToFileURL(path.join(runtime, 'apps/cli/package.json')).href);
try {
  const tools = ctx.get('tools');
  const invoke = command => tools.execute({name: 'pwsh', arguments: {command,
    description: 'Offline integrated public interface acceptance'}, callId: randomUUID(), signal: new AbortController().signal});
  const metadata = await invoke('& $env:C3_PYTHON -B common/client.py runtime; exit $LASTEXITCODE');
  assert(!metadata.isError && metadata.value.exitCode === 0);
  const runtimeView = JSON.parse(metadata.value.stdout.text);
  assert.equal(runtimeView.state, 'runtime_identity');
  assert.equal(runtimeView.runtime.version, '9');
  const failure = await invoke("Write-Output 'controlled-integration-failure'; exit 7");
  assert(failure.isError);
  const original = JSON.parse(failure.content[0].text.split('\n')[1]).originalValue;
  assert.equal(original.exitCode, 7);
  assert(original.stdout.text.includes('controlled-integration-failure'));
  assert(!fs.existsSync('exchange/request.json'));
  fs.writeFileSync(path.join(root, 'integration-probe.json'), JSON.stringify({passed: true,
    model_calls: 0, node_jobs: 0, tools: [...tools.view().visible.keys()].sort(),
    metadata, failure, registered_request: false}, null, 2), {flag: 'wx'});
} finally { await ctx.fiber.dispose(); }
