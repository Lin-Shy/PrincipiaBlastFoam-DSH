// Inspect an already prepared offline profile without model or shell dispatch.
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
const [runtime, root] = process.argv.slice(2);
const load = p => import(pathToFileURL(path.join(runtime, p)).href);
const {boot, loadLayeredEnv} = await load('packages/boot/app-boot/lib/index.js');
const {DSH_LAUNCH_ENVIRONMENT_KEY: key} = await load('packages/util/launch-environment/lib/index.js');
const ctx = await boot('c3-error-inspect', path.join(root, 'boot.yml'),
  ['headless-startup', 'headless-runner'].map(id => ({id, disabled: true})),
  c => c.provide(key, loadLayeredEnv('c3-error-inspect')),
  pathToFileURL(path.join(runtime, 'apps/cli/package.json')).href);
try {
  const names = [...ctx.get('tools').view().visible.keys()].sort();
  assert(names.includes('pwsh'));
  const mcp = names.filter(name => name.startsWith('mcp__'));
  assert.equal(mcp.length, 0);
  fs.writeFileSync(path.join(root, 'inspection.json'), JSON.stringify({
    visible_tools: names, mcp_tools: mcp, mcp_status: 'No MCP instance configured or connected in this offline profile',
    model_calls: 0, node_jobs: 0, passed: true}, null, 2), {flag: 'wx'});
} finally { await ctx.fiber.dispose(); }
