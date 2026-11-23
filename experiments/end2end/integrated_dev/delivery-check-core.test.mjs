import {test} from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {createHash} from 'node:crypto';
import {verifyManifest} from './delivery-check-core.mjs';

function fixture(t) {
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'delivery-check-'));
  t.after(()=>{
    assert.equal(fs.realpathSync(path.dirname(root)),fs.realpathSync(os.tmpdir()));
    assert(path.basename(root).startsWith('delivery-check-'));
    assert.equal(fs.realpathSync(root),path.resolve(root));
    fs.rmSync(root,{recursive:true,force:true});
  });
  fs.mkdirSync(path.join(root,'data'));
  fs.writeFileSync(path.join(root,'data/a'),'alpha');
  return {root,sha:createHash('sha256').update('alpha').digest('hex'),
    manifest(files){fs.writeFileSync(path.join(root,'receipt.json'),JSON.stringify({files}));}};
}

test('reports numeric counts, differences and missing paths without modifying inputs',t=>{
  const f=fixture(t);f.manifest({a:f.sha,missing:f.sha});
  const before=fs.readFileSync(path.join(f.root,'data/a'));
  const out=verifyManifest(f.root,'receipt.json','data');
  assert.equal(out.expected_count,2);assert.equal(out.matched_count,1);assert.equal(out.missing_count,1);
  assert.deepEqual(fs.readFileSync(path.join(f.root,'data/a')),before);
  assert(!fs.existsSync(path.join(f.root,'data/missing')));
  f.manifest({a:'0'.repeat(64)});
  assert.equal(verifyManifest(f.root,'receipt.json','data').mismatched_count,1);
});
test('empty and malformed identities cannot return success',t=>{
  const f=fixture(t);f.manifest({});assert.throws(()=>verifyManifest(f.root,'receipt.json','data'));
  f.manifest({a:'not-a-hash'});assert.throws(()=>verifyManifest(f.root,'receipt.json','data'));
});
test('parent paths and linked directories cannot expose other files',t=>{
  const f=fixture(t);f.manifest({'../receipt.json':f.sha});
  assert.equal(verifyManifest(f.root,'receipt.json','data').unreadable_count,1);
  assert.throws(()=>verifyManifest(f.root,'../receipt.json','data'));
  fs.symlinkSync(path.join(f.root,'data'),path.join(f.root,'linked'),'junction');
  assert.throws(()=>verifyManifest(f.root,'receipt.json','linked'));
});
test('cancellation stops before checking a file',t=>{
  const f=fixture(t);f.manifest({a:f.sha});const controller=new AbortController();controller.abort();
  assert.throws(()=>verifyManifest(f.root,'receipt.json','data',controller.signal),{name:'AbortError'});
});
