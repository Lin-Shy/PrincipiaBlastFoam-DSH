// A model-facing directory discovery tool with no shell or mutation capability.
import { posix } from 'node:path'

export const name = 'principia-readonly-directory'
export const inject = ['tools', 'fs']

export function directoryTool(fs, workspace) {
  const roots = [workspace, '/data/OpenFOAM/blastfoam', '/data/OpenFOAM/OpenFOAM-9']
  return {
    name: 'principia_list_directory',
    description: 'Read-only directory listing for the active task workspace and installed OpenFOAM/blastFoam documentation/source. Use this to discover real paths before read; do not guess tutorial paths. Returns at most 500 names and types, no file content or shell execution.',
    parameters: { type: 'object', properties: { path: { type: 'string', description: 'Absolute remote directory path.' } }, required: ['path'], additionalProperties: false },
    output: { schema: { type: 'object' }, render: (_args, value) => [{ type: 'text', text: JSON.stringify(value) }] },
    async execute(args, exec) {
      if (typeof args?.path !== 'string' || !posix.isAbsolute(args.path)) throw new Error('Absolute remote directory required')
      const path = posix.normalize(args.path)
      if (!roots.some(root => path === root || path.startsWith(root + '/'))) throw new Error('Directory outside active workspace and installed documentation roots')
      const target = await fs.resolve(path, { cwd: workspace, signal: exec.signal })
      const entries = await fs.listDir(target, exec.signal)
      const sorted = entries.map(e => ({ name: e.name, type: e.type })).sort((a, b) => a.name.localeCompare(b.name))
      return { path, entries: sorted.slice(0, 500), truncated: sorted.length > 500 }
    },
  }
}

export function apply(ctx, config) {
  if (typeof config?.workspace !== 'string' || !posix.isAbsolute(config.workspace)) throw new Error('Active remote workspace required')
  ctx.tools.register(directoryTool(ctx.fs, posix.normalize(config.workspace)))
}
