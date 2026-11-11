// Exercise the actual manager/router composition with local fallback forbidden.
import { createRequire } from 'node:module'
import { pathToFileURL } from 'node:url'
import { resolve } from 'node:path'
import { readFile } from 'node:fs/promises'
import { directoryTool } from './readonly_directory.mjs'

const [pluginRoot, runDir, existingWorkspace] = process.argv.slice(2)
const require = createRequire(resolve(pluginRoot, 'package.json'))
const load = async name => import(pathToFileURL(require.resolve(name)).href)
const { Context, Service } = await load('@deepseek-ai/cordis')
const { default: Settings } = await load('@deepseek-ai/dsh-settings-file')
const { default: Manager } = await load('dsh-remote-ssh/manager')
const { default: Router } = await load('dsh-remote-ssh/router-fs')
class RejectLocal extends Service {
  constructor(ctx) { super(ctx, 'localFs') }
  resolve() { throw new Error('Unexpected local Windows fallback') }
}
const patch = JSON.parse(await readFile(resolve(runDir, 'runtime/development.patch.yml'), 'utf8'))
const config = patch.find(row => row.id === 'remote-ssh-manager').config
if (existingWorkspace) config.workspaces[0].remotePath = existingWorkspace
const workspace = config.workspaces[0].remotePath
const ctx = new Context()
try {
  await ctx.plugin(Settings, { path: resolve(runDir, 'routing-probe-settings.json'), watch: false }).await()
  await ctx.plugin(RejectLocal).await()
  await ctx.plugin(Manager, config).await()
  await ctx.plugin(Router).await()
  const signal = new AbortController().signal
  const root = await ctx.fs.resolve('/data/OpenFOAM/blastfoam', { signal })
  const entries = await ctx.fs.listDir(root, signal)
  const readme = entries.find(e => e.name === 'README.md')
  if (!readme || !(await ctx.fs.readText(readme.target, signal)).length) throw new Error('Installed README not readable')
  const listing = await directoryTool(ctx.fs, workspace).execute({ path: workspace + '/public' }, { signal })
  if (!listing.entries.some(e => e.name === 'request.md')) throw new Error('Task path not routed')
  console.log(JSON.stringify({ transparentRoutingPassed: true, installedDocsRead: true,
    taskDirectoryListed: true, localFallbackAllowed: false }))
} finally { await ctx.fiber.dispose() }
