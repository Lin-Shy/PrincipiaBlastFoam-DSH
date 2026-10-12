import test from 'node:test';
import assert from 'node:assert/strict';
import { latestUserRequest, apply } from './native_request_context.mjs';
const user = text => ({ type: 'user/message', data: { source: { kind: 'user' }, content: [{ type: 'text', text }] } });
test('only actual latest user text, no plugin/tool text or truncation', () => {
  assert.equal(latestUserRequest([user('old'),user('new'),{type:'user/message',data:{source:{kind:'plugin'},content:[{type:'text',text:'fake'}]}}]),'new');
  assert.equal(latestUserRequest([user('x'.repeat(32769))]),'');
  assert.equal(latestUserRequest([]),'');
});
test('scoped adapter preserves model call and isolates session context', async () => {
  const calls=[];let created;const wrappers=[];
  const original={name:'locator',parameters:{properties:{query:{},original_request:{}},required:['query']},execute:async (args,exec)=>{calls.push(args);return args;}};
  apply({tools:{get:()=>original},on:(name,cb)=>{assert.equal(name,'agent/created');created=cb;}});
  for(let i=0;i<2;i++)created({agent:{ctx:{tools:{register:t=>wrappers.push(t)}}}});
  const args=Object.freeze({query:'shortened',original_request:'model-forged'});
  await Promise.all(wrappers.map((w,i)=>w.execute(args,{agent:{session:{snapshotEvents:()=>[user('task-'+i)]}}})));
  assert.deepEqual(calls.map(c=>c.original_request),['task-0','task-1']);
  assert.equal(args.original_request,'model-forged');assert.ok(!('original_request' in wrappers[0].parameters.properties));
  assert.ok('original_request' in original.parameters.properties);
});
test('file navigation is opt-in and uses the same real request context', async () => {
 let created;const wrappers=[];const calls=[];
 const ctx={tools:{get:name=>({name,description:'tool',parameters:{properties:{case_path:{},original_request:{}}},execute:async args=>{calls.push({name,args});return args;}})},on:(_n,cb)=>{created=cb;}};
 apply(ctx,{fileNavigation:true});created({agent:{ctx:{tools:{register:t=>wrappers.push(t)}}}});
 assert.equal(wrappers.length,2);
 const file=wrappers.find(t=>t.name.endsWith('get_files_for_case'));
 await file.execute({case_path:'demo'},{agent:{session:{snapshotEvents:()=>[user('real task')]}}});
 assert.deepEqual(calls[0].args,{case_path:'demo',original_request:'real task'});
});
