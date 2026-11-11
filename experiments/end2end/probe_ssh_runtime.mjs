// Exercise the installed SSH runtime without a model request or solver command.
import { createRequire } from 'node:module'
import { pathToFileURL } from 'node:url'
import { resolve } from 'node:path'

const [pluginRoot, host, remoteWorkspace, localWorkspace, remoteCodeCommand] = process.argv.slice(2)
const require = createRequire(resolve(pluginRoot, 'package.json'))
const { Context } = await import(pathToFileURL(require.resolve('@deepseek-ai/cordis')).href)
const { default: Runtime } = await import(pathToFileURL(resolve(pluginRoot, 'lib/index.js')).href)
const ctx = new Context()
try {
  await ctx.plugin(Runtime, { sshTarget: host, remoteWorkspace, localWorkspace,
    remoteCodeCommand, sshArgs: ['-o', 'BatchMode=yes'], startupTimeoutMs: 60000 }).await()
  const connection = await ctx.remoteSsh.getConnection()
  const result = await connection.client.resourceResolve({ uri: `file://${remoteWorkspace}/public/request.md` })
  console.log(JSON.stringify({ protocolVersion: connection.protocolVersion, taskReadable: Boolean(result) }))
  const { default: RemoteFs } = await import(pathToFileURL(require.resolve('dsh-remote-ssh/fs')).href)
  await ctx.plugin(RemoteFs, { localWorkspace, remoteWorkspace }).await()
  const { directoryTool } = await import('./readonly_directory.mjs')
  const tool = directoryTool(ctx.fs, remoteWorkspace)
  const listing = await tool.execute({ path: '/data/OpenFOAM/blastfoam' }, { signal: new AbortController().signal })
  if (!listing.entries.some(entry => entry.name === 'tutorials')) throw new Error('Installed docs directory not visible')
  console.log(JSON.stringify({ readonlyDirectoryProbe: true, installedDocsDiscoverable: true }))
} finally {
  await ctx.fiber.dispose()
}
