import test from 'node:test'
import assert from 'node:assert/strict'
import { directoryTool } from '../experiments/end2end/readonly_directory.mjs'

test('rejects other task directories and traversal before filesystem access', async () => {
  const fs = new Proxy({}, { get() { throw new Error('Filesystem must not be reached') } })
  const tool = directoryTool(fs, '/data/task/current')
  for (const path of ['/data/task/previous', '/data/task/current/../previous', '/etc', 'relative']) {
    await assert.rejects(tool.execute({ path }, { signal: new AbortController().signal }), /outside|Absolute/)
  }
})

test('uses routed filesystem listing and exposes no contents or mutation', async () => {
  const signal = new AbortController().signal
  const calls = []
  const fs = {
    async resolve(path, opts) { calls.push(['resolve', path]); assert.equal(opts.signal, signal); assert.equal(opts.cwd, '/data/task/current'); return { displayPath: path } },
    async listDir(target, receivedSignal) { calls.push(['list', target.displayPath]); assert.equal(receivedSignal, signal); return Array.from({ length: 501 }, (_, i) => ({ name: `file${i}`, type: 'file', content: 'must not leak' })) },
  }
  const result = await directoryTool(fs, '/data/task/current').execute({ path: '/data/OpenFOAM/blastfoam' }, { signal })
  assert.equal(result.entries.length, 500)
  assert.equal(result.truncated, true)
  assert.equal(JSON.stringify(result).includes('must not leak'), false)
  assert.deepEqual(calls, [['resolve', '/data/OpenFOAM/blastfoam'], ['list', '/data/OpenFOAM/blastfoam']])
})
