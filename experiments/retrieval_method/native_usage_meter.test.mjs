import test from 'node:test';
import assert from 'node:assert/strict';
import {metered} from './native_usage_meter.mjs';

test('agent and auxiliary usage pass through without changing stream chunks',async()=>{
 for(const purpose of [undefined,'session-title','compaction']) {
  const chunks=[{type:'text-delta',text:'private content'},
   {type:'usage',usage:{inputTokens:10,cacheReadTokens:30,outputTokens:4,totalTokens:44}},
   {type:'finish',reason:{kind:'stop'}}];const rows=[];
  async function* input(){yield* chunks;}
  const result=[];for await(const c of metered(input(),{purpose,model:'fixture'},r=>rows.push(r),'id'))result.push(c);
  assert.deepEqual(result,chunks);assert.equal(result[0],chunks[0]);
  assert.equal(rows.at(-1).purpose,purpose??'agent');assert.equal(rows.at(-1).usage.totalTokens,44);
  assert.equal(rows.at(-1).terminal_observed,true);assert.equal(rows.at(-1).finish_kind,'stop');assert.ok(!JSON.stringify(rows).includes('private content'));
 }
});

test('failed stream is counted and unreported usage is unknown',async()=>{
 const rows=[];async function* input(){throw new TypeError('secret transport details');}
 await assert.rejects(async()=>{for await(const c of metered(input(),{},r=>rows.push(r),'failed')){}},TypeError);
 assert.equal(rows.length,2);assert.equal(rows.at(-1).error_name,'TypeError');assert.equal(rows.at(-1).usage,null);
 assert.ok(!JSON.stringify(rows).includes('secret transport details'));
});

test('consumer cancellation preserves partial usage without claiming completion',async()=>{
 const rows=[];async function* input(){yield {type:'usage',usage:{outputTokens:3}};yield {type:'finish'};}
 for await(const c of metered(input(),{},r=>rows.push(r),'cancelled'))break;
 assert.equal(rows.at(-1).terminal_observed,false);assert.equal(rows.at(-1).usage.outputTokens,3);
});
