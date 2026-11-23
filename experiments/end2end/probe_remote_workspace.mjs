// Maintenance acceptance of the installed DSH SSH routers. No model or solver.
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';

const [profile, evidence] = process.argv.slice(2);
const config = JSON.parse(fs.readFileSync(path.join(evidence, 'probe-config.json'), 'utf8'));
const require = createRequire(path.join(path.resolve(profile), 'package.json'));
const load = name => import(pathToFileURL(require.resolve(name)).href);
const {Context} = await load('@deepseek-ai/cordis');
const {SettingsProvider} = await load('@deepseek-ai/dsh-settings');
const {default: Manager} = await load('dsh-remote-ssh/manager');
const {default: Router} = await load('dsh-remote-ssh/router-fs');
const {default: Processes} = await load('dsh-remote-ssh/router-subprocess');
class MemorySettings extends SettingsProvider {
  get writable() { return true; }
  async load() { return {}; }
  async persist() {}
}
const report = {started_utc: new Date().toISOString(), model_calls: 0, node_jobs: 0,
  plugin_version: require('dsh-remote-ssh/package.json').version, checks: []};
const content = 'FoamFile\n{ version 2.0; format ascii; class dictionary; object controlDict; }\napplication icoFoam;\nstartFrom startTime;\nstartTime 0;\nstopAt endTime;\nendTime 0.1;\ndeltaT 0.001;\nwriteControl timeStep;\nwriteInterval 50;\n';
const check = (name, details = {}) => {
  report.checks.push({name, passed: true, ...details});
  fs.writeFileSync(path.join(evidence, 'probe-result.json'), JSON.stringify(report, null, 2));
  console.log(JSON.stringify({name, passed: true}));
};
async function open() {
  const ctx = new Context();
  await ctx.plugin(MemorySettings).await();
  ctx.provide('localFs', new Proxy({}, {get() { return () => { throw new Error('Local filesystem fallback forbidden'); }; }}));
  ctx.provide('localSubprocess', new Proxy({}, {get() { return () => { throw new Error('Local subprocess fallback forbidden'); }; }}));
  await ctx.plugin(Manager, {aliasRoot: path.join(evidence, 'aliases'), startupTimeoutMs: 60000,
    requestTimeoutMs: 15000,
    servers: [{id: 'probe', label: 'Maintenance probe', sshTarget: config.host,
      sshArgs: ['-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=12'],
      remoteCodeCommand: config.code}],
    workspaces: [{id: 'probe', serverId: 'probe', remotePath: config.remote_workspace}],
  }).await();
  await ctx.plugin(Router).await();
  await ctx.plugin(Processes).await();
  return ctx;
}
async function command(ctx, argv) {
  const route = ctx.remoteSshManager.workspace('probe');
  const handle = ctx.subprocess.spawn({argv, cwd: route.aliasPath,
    stdio: {stdin: 'ignore', stdout: {maxBytes: 16384}, stderr: {maxBytes: 16384}},
    graceMs: 1000, signal: AbortSignal.timeout(20000)});
  const outcome = await handle.done;
  return {...outcome, stdout: handle.collected.stdout?.readFrom(0).text,
    stderr: handle.collected.stderr?.readFrom(0).text};
}
let ctx;
try {
  ctx = await open();
  const route = ctx.remoteSshManager.workspace('probe');
  assert.equal(route.kind, 'remote');
  assert.equal(ctx.remoteSshManager.dialectFor(route.aliasPath), 'bash');
  const connected = await ctx.remoteSshManager.workspaceContext(route);
  const connection = await connected.remote.getConnection();
  check('installed_router_connected', {protocol: connection.protocolVersion});
  const identity = await command(ctx, ['bash', '-c', 'printf "IDENTITY="; id -un; printf "CWD="; pwd; printf "SYSTEM="; uname -s']);
  assert.equal(identity.exitCode, 0);
  assert(identity.stdout.includes(config.remote_workspace));
  assert(identity.stdout.includes('Linux'));
  check('remote_command_identity', {result: identity});
  const directories = await command(ctx, ['mkdir', '-p', 'case/system', 'case/constant', 'case/0']);
  assert.equal(directories.exitCode, 0);
  const target = await ctx.fs.resolve('case/system/controlDict', {cwd: route.aliasPath});
  await ctx.fs.writeText(target, content, {kind: 'createIfAbsent'});
  assert.equal(await ctx.fs.readText(target), content);
  const digest = createHash('sha256').update(content).digest('hex');
  check('case_write_read', {sha256: digest, local_fallback: false});
  const hash = await command(ctx, ['sha256sum', 'case/system/controlDict']);
  assert.equal(hash.exitCode, 0);
  assert(hash.stdout.startsWith(digest));
  check('remote_hash_matches', {result: hash});
  const search = await command(ctx, ['rg', '-n', 'application icoFoam', 'case']);
  assert.equal(search.exitCode, 0);
  assert(search.stdout.includes('controlDict:'));
  check('remote_search', {result: search});
  const failure = await command(ctx, ['bash', '-c', 'printf probe-stdout; printf probe-stderr >&2; exit 7']);
  assert.equal(failure.exitCode, 7);
  assert.equal(failure.stdout, 'probe-stdout');
  assert.equal(failure.stderr, 'probe-stderr');
  check('nonzero_and_separate_stderr', {result: failure});
  await ctx.fiber.dispose();
  ctx = undefined;
  check('client_closed_cleanly');
  ctx = await open();
  const restored = ctx.remoteSshManager.workspace('probe');
  const reopened = await ctx.fs.resolve('case/system/controlDict', {cwd: restored.aliasPath});
  assert.equal(await ctx.fs.readText(reopened), content);
  check('fresh_client_reads_persisted_case');
  const refused = path.join(evidence, 'aliases', 'probe', 'case', 'system', 'controlDict');
  assert(!fs.existsSync(refused));
  check('no_local_case_copy');
  report.passed = true;
} catch (error) {
  report.passed = false;
  report.error = {name: error.name, message: error.message, stack: error.stack};
  process.exitCode = 1;
} finally {
  if (ctx) await ctx.fiber.dispose();
  report.finished_utc = new Date().toISOString();
  fs.writeFileSync(path.join(evidence, 'probe-result.json'), JSON.stringify(report, null, 2));
}
