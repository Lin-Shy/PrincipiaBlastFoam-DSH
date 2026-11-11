// No model and no solver: use the actual pooled AHP shell/fs, then disconnect.
import { createRequire } from 'node:module'
import { pathToFileURL } from 'node:url'
import { resolve } from 'node:path'
import { readFile } from 'node:fs/promises'

const [pluginRoot, runDir, remoteWorkspace, action, ...args] = process.argv.slice(2)
const require = createRequire(resolve(pluginRoot, 'package.json'))
const load = async name => import(pathToFileURL(require.resolve(name)).href)
const { Context, Service } = await load('@deepseek-ai/cordis')
const { default: Settings } = await load('@deepseek-ai/dsh-settings-file')
const { default: Manager } = await load('dsh-remote-ssh/manager')
const { default: Router } = await load('dsh-remote-ssh/router-fs')
class RejectLocal extends Service {
  constructor(ctx) { super(ctx, 'localFs') }
  resolve() { throw new Error('Unexpected local filesystem fallback') }
}
const patch = JSON.parse(await readFile(resolve(runDir, 'runtime/development.patch.yml'), 'utf8'))
const original = patch.find(row => row.id === 'remote-ssh-manager').config
const config = { ...original, aliasRoot: resolve(runDir, 'guard-probe-aliases'), workspaces: [{ id: 'guard-probe', serverId: 'development',
  remotePath: remoteWorkspace, aliasPath: resolve(runDir, 'guard-probe-alias') }] }
const ctx = new Context()
const quote = value => `'${value.replaceAll("'", "'\"'\"'")}'`
try {
  await ctx.plugin(Settings, { path: resolve(runDir, 'guard-probe-settings.json'), watch: false }).await()
  await ctx.plugin(RejectLocal).await()
  await ctx.plugin(Manager, config).await()
  await ctx.plugin(Router).await()
  const signal = new AbortController().signal
  if (action === 'start') {
    const [name, scenario, timeout = '30', budget = '120'] = args
    if (![name, scenario].every(x => /^[a-z0-9_-]+$/.test(x))) throw new Error('Invalid probe name')
    const command = ['/data/miniconda3/bin/python3', `${remoteWorkspace}/guarded_remote_job.py`, 'start',
      '--job', `${remoteWorkspace}/jobs/${name}`, '--workspace', remoteWorkspace, '--cwd', remoteWorkspace,
      '--timeout-seconds', timeout, '--budget-seconds', budget, '--',
      '/data/miniconda3/bin/python3', `${remoteWorkspace}/mock_process.py`, scenario].map(quote).join(' ')
    const route = ctx.remoteSshManager.route(undefined, remoteWorkspace)
    const shell = await ctx.remoteSshManager.workspaceShell(route, 'bash')
    const result = await shell.run(shell.resolve({ command, workdir: remoteWorkspace, timeoutMs: 20000, signal }))
    if (result.exitCode !== 0) throw new Error(JSON.stringify(result))
    console.log(JSON.stringify({ action, scenario, result: result.stdout.text,
      connectionWillBeDisposed: true, modelCalls: 0, solverCalls: 0 }))
  } else if (action === 'status') {
    const [name] = args
    if (!/^[a-z0-9_-]+$/.test(name)) throw new Error('Invalid job name')
    const target = await ctx.fs.resolve(`${remoteWorkspace}/jobs/${name}/status.json`, { signal })
    console.log(JSON.stringify({ action, name, status: JSON.parse(await ctx.fs.readText(target, signal)),
      readAfterNewAhpConnection: true, localFallbackAllowed: false }))
  } else throw new Error('Use start or status')
} finally { await ctx.fiber.dispose() }
