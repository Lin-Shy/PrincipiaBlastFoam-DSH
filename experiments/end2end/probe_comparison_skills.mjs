// Inspect explicit local catalogs only; no model, SSH, solver or profile mutation.
import { FileSystemSkillProvider } from '../../../../deepseek-harness/packages/skill/skill-filesystem/lib/index.js'
import { resolve } from 'node:path'
const pair = resolve(process.argv[2]);
const results = [];
for (const arm of ['general', 'professional']) {
  let routedAccesses = 0;
  const remoteFs = new Proxy({}, { get() { routedAccesses++; throw new Error('unexpected routed filesystem'); } });
  const ctx = { get() { return remoteFs; }, logger: { warn: console.warn } };
  const provider = new FileSystemSkillProvider(ctx, { signal: new AbortController().signal, invalidate() {} }, {
    includeDefaultRoots: false, customSkillDirs: [], bundledSkillDir: resolve(pair, arm, 'skills'),
    dshHome: resolve(pair, arm, 'home'), agentsHome: resolve(pair, arm, 'agents_home'), watch: false,
  });
  try {
    const listed = await provider.list({ cwd: resolve(pair, arm, 'workspace') });
    const candidates = Array.isArray(listed) ? listed : listed.candidates;
    const expected = arm === 'general' ? [] : ['blastfoam-professional'];
    if (JSON.stringify(candidates.map(x => x.name).sort()) !== JSON.stringify(expected)) throw new Error('unexpected skill catalog');
    for (const c of candidates) {
      const skill = await provider.get(c, {});
      if (!skill.content.includes('cluster_job.py')) throw new Error('skill body missing');
    }
    results.push({ arm, skills: expected, bodiesLoaded: true, routedAccesses });
  } finally { await provider.dispose(); }
}
console.log(JSON.stringify(results, null, 2));
