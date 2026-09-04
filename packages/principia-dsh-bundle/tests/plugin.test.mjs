import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import test from 'node:test'
import { apply, inject, name, PRINCIPIA_POLICY } from '../lib/index.js'

test('registers one TEAM_POLICY section', () => {
  const sections = []
  const ctx = {
    systemPrompt: {
      getSectionOrder(orderName) {
        assert.equal(orderName, 'TEAM_POLICY')
        return 600
      },
      section(section) {
        sections.push(section)
        return () => undefined
      },
    },
  }

  apply(ctx)
  assert.equal(name, 'principia-blastfoam-policy')
  assert.deepEqual(inject, ['systemPrompt'])
  assert.deepEqual(sections, [{
    name: 'principia-blastfoam:workflow-policy',
    order: 600,
    text: PRINCIPIA_POLICY,
  }])
})

test('bundle manifest and patch keep stable install seams', async () => {
  const manifest = JSON.parse(await readFile(new URL('../package.json', import.meta.url), 'utf8'))
  const patch = await readFile(new URL('../cordis.patch.yml', import.meta.url), 'utf8')

  assert.equal(manifest.dsh.bundle.patch, './cordis.patch.yml')
  assert.equal(manifest.main, 'lib/index.js')
  assert.equal(manifest.dependencies, undefined)
  assert.match(patch, /name: principia-blastfoam-dsh-bundle/)
  assert.match(patch, /name: '@deepseek-ai\/dsh-mcp-client'/)
  assert.match(patch, /provider: spawn/)
  assert.match(patch, /toolName: blastfoam_quality_reviewer/)
  assert.match(patch, /PRINCIPIA_CASE_ROOT:/)
  assert.match(patch, /BLASTFOAM_TUTORIALS:/)
  assert.match(patch, /ENABLE_EXECUTION: !!js process\.env\.ENABLE_EXECUTION \?\? 'true'/)
  assert.match(patch, /REQUIRE_EXECUTION: !!js process\.env\.REQUIRE_EXECUTION \?\? 'true'/)
  assert.match(patch, /OPENFOAM_EXECUTION_USER:/)
  assert.match(patch, /toolName: blastfoam_quality_reviewer[\s\S]*?allow: \[read, glob, grep, skill\]/)
  assert.doesNotMatch(patch, /toolFilter:\n\s+deny:/)
  assert.doesNotMatch(patch, /\/data\/|\/home\/|~\//)
})

test('role allowlists preserve least-privilege boundaries', async () => {
  const patch = await readFile(new URL('../cordis.patch.yml', import.meta.url), 'utf8')
  const roleBlock = (id) => {
    const start = patch.indexOf(`    - id: ${id}\n`)
    assert.notEqual(start, -1, `missing role row ${id}`)
    const next = patch.indexOf('\n    - id: ', start + 1)
    return patch.slice(start, next === -1 ? patch.length : next)
  }

  const physics = roleBlock('principia-physics-analyst')
  const setup = roleBlock('principia-case-setup')
  const execution = roleBlock('principia-execution-specialist')
  const postprocessor = roleBlock('principia-postprocessor')
  const reviewer = roleBlock('principia-reviewer')

  for (const [role, block] of [
    ['physics', physics],
    ['execution', execution],
    ['reviewer', reviewer],
  ]) {
    assert.doesNotMatch(block, /\n\s+- (?:bash|write|edit|str_replace_editor)\s*$/m, `${role} gained mutation capability`)
  }

  assert.doesNotMatch(setup, /\n\s+- bash\s*$/m)
  assert.match(setup, /\n\s+- write\s*$/m)
  assert.match(setup, /\n\s+- edit\s*$/m)

  assert.match(postprocessor, /\n\s+- bash\s*$/m)
  assert.doesNotMatch(postprocessor, /\n\s+- (?:write|edit|str_replace_editor)\s*$/m)

  assert.match(reviewer, /allow: \[read, glob, grep, skill\]/)
})
