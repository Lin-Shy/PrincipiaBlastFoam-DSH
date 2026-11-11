// Prove workflow discovery and body loading do not touch the SSH filesystem.
import { FileSystemSkillProvider } from '../../../../deepseek-harness/packages/skill/skill-filesystem/lib/index.js'
import { resolve } from 'node:path'

let routedAccesses = 0
const remoteFs = new Proxy({}, { get() { routedAccesses++; throw new Error('Unexpected routed filesystem access') } })
const ctx = { get: () => remoteFs, logger: { warn: console.warn } }
const abort = new AbortController()
const provider = new FileSystemSkillProvider(ctx, { signal: abort.signal, invalidate() {} }, {
  includeDefaultRoots: false, bundledSkillDir: resolve(process.argv[2]), watch: false,
})
try {
  const result = await provider.list({ cwd: resolve('.') })
  const candidates = Array.isArray(result) ? result : result.candidates
  if (candidates.length !== 1 || candidates[0].name !== 'blastfoam-workflow') throw new Error('Wrong local workflow catalog')
  const skill = await provider.get(candidates[0], {})
  if (!skill?.content.includes('blastfoam_case_setup')) throw new Error('Missing workflow body')
  console.log(JSON.stringify({ skill: skill.name, bodyLoaded: true, routedFilesystemAccesses: routedAccesses }))
} finally { await provider.dispose() }
