import fs from 'node:fs';
import path from 'node:path';
import {createHash} from 'node:crypto';

function inside(root, candidate) {
  const relative = path.relative(root, candidate);
  return relative === '' || (!path.isAbsolute(relative) && relative !== '..' && !relative.startsWith('..' + path.sep));
}

function checkedPath(root, relative) {
  if (typeof relative !== 'string' || path.isAbsolute(relative) || relative.split(/[\\/]/).includes('..')) {
    throw Error('Use a relative path without parent traversal');
  }
  const target = path.resolve(root, relative);
  if (!inside(root, target)) throw Error('Path outside selected directory');
  let current = root;
  for (const part of path.relative(root, target).split(path.sep).filter(Boolean)) {
    current = path.join(current, part);
    if (fs.lstatSync(current).isSymbolicLink()) throw Error('Linked paths are not supported');
  }
  return target;
}

/** Read-only, bounded file identity check. Never creates a receipt or delivery. */
export function verifyManifest(workspace, manifest, directory, signal) {
  const root = fs.realpathSync(workspace);
  const manifestPath = checkedPath(root, manifest);
  const base = checkedPath(root, directory);
  if (!fs.statSync(base).isDirectory()) throw Error('directory must name a directory');
  if (fs.statSync(manifestPath).size > 2 * 1024 * 1024) throw Error('Manifest exceeds 2 MiB');
  const raw = fs.readFileSync(manifestPath);
  const data = JSON.parse(raw.toString('utf8').replace(/^\uFEFF/, ''));
  if (!data.files || typeof data.files !== 'object' || Array.isArray(data.files)) throw Error('Expected a files object mapping relative paths to SHA256');
  const entries = Object.entries(data.files).sort(([a], [b]) => a.localeCompare(b));
  if (!entries.length || entries.length > 10000) throw Error('Manifest requires 1 to 10000 files');
  const missing = [], mismatched = [], unreadable = [];
  let matched = 0, bytes = 0;
  for (const [name, expected] of entries) {
    signal?.throwIfAborted();
    if (typeof expected !== 'string' || !/^[a-f0-9]{64}$/i.test(expected)) throw Error('Invalid SHA256 for ' + name);
    try {
      const file = checkedPath(base, name);
      const before = fs.statSync(file);
      if (!before.isFile()) throw Error('Not a regular file');
      if (before.size > 32 * 1024 * 1024 || bytes + before.size > 128 * 1024 * 1024) throw Error('Read size limit exceeded');
      const content = fs.readFileSync(file);
      bytes += content.length;
      const after = fs.statSync(file);
      if (before.size !== after.size || before.mtimeMs !== after.mtimeMs) throw Error('File changed during check');
      const actual = createHash('sha256').update(content).digest('hex');
      if (actual === expected.toLowerCase()) matched++;
      else mismatched.push({path: name, expected, actual});
    } catch (error) {
      if (error.code === 'ENOENT') missing.push(name);
      else unreadable.push({path: name, reason: error.message});
    }
  }
  return {status: matched === entries.length ? 'all_matched' : 'differences', expected_count: entries.length,
    matched_count: matched, missing_count: missing.length, mismatched_count: mismatched.length,
    unreadable_count: unreadable.length, missing, mismatched, unreadable,
    manifest_sha256: createHash('sha256').update(raw).digest('hex'), bytes_read: bytes,
    scope: 'Only listed file identities checked; not a complete-delivery or numerical-correctness verdict'};
}

export function canonical(value) {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === 'object') return Object.fromEntries(Object.keys(value).sort().map(key => [key, canonical(value[key])]));
  return value;
}
