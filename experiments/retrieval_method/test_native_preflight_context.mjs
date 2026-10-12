import test from 'node:test';
import assert from 'node:assert/strict';
import {taskCache,attachNavigation,currentTask} from './native_preflight_context.mjs';
test('claimed user task is available before session commit and replaces stale tasks',()=>{
 let claim;const events=[];
 const now=currentTask({ctx:{on:(name,fn)=>{assert.equal(name,'agent/inbox/claimed');claim=fn;}},session:{snapshotEvents:()=>events}});
 const message=(text,kind='user')=>({source:{kind},content:[{type:'text',text}]});
 assert.equal(now(),'');
 claim({message:message('first task')});assert.equal(now(),'first task');assert.equal(events.length,0);
 events.push({type:'user/message',data:message('old persisted task')});
 claim({message:message('plugin text','plugin')});assert.equal(now(),'first task');
 claim({message:message('unrelated task')});assert.equal(now(),'unrelated task');
 claim({message:message('x'.repeat(32769))});assert.equal(now(),'');
});
test('one query per current actual task; empty request does not query',async()=>{
 let calls=0;const load=taskCache(async text=>{calls++;return {text};});
 assert.equal(await load(''),null);
 const [a,b]=await Promise.all([load('first'),load('first')]);assert.equal(calls,1);assert.equal(a,b);
 await load('second');assert.equal(calls,2);
});
test('only data context and a literal-substitution variable are changed',()=>{
 const a={sections:[{name:'system',text:'original'}],tools:['tool'],variables:{existing:'x'},contexts:[]};
 const originalSections=a.sections,originalTools=a.tools;
 attachNavigation(a,{status:'located',value:'{{untrusted}}'});
 assert.equal(a.sections,originalSections);assert.equal(a.tools,originalTools);
 assert.equal(a.contexts.length,1);assert(a.variables.principia_task_navigation_packet.includes('{{untrusted}}'));
 attachNavigation(a,{status:'located'});assert.equal(a.contexts.length,1);
 const skipped={contexts:[],variables:{}};assert.equal(attachNavigation(skipped,{status:'not_applicable'}),skipped);assert.equal(skipped.contexts.length,0);
});
test('cancelled attempt can be retried rather than leaving a rejected cache',async()=>{
 let n=0;const load=taskCache(async()=>{if(++n===1)throw Error('cancelled');return 'ok';});
 await assert.rejects(load('task'));assert.equal(await load('task'),'ok');assert.equal(n,2);
});
