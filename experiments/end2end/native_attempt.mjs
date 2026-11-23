// Thin launcher over native DSH boot/Agent/session APIs. No custom agent algorithm.
import fs from 'node:fs';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {randomUUID} from 'node:crypto';
const [root,runtime,overlay,promptFile]=process.argv.slice(2);
const load=p=>import(pathToFileURL(path.join(runtime,p)).href);
const {boot,loadLayeredEnv}=await load('packages/boot/app-boot/lib/index.js');
const {DSH_LAUNCH_ENVIRONMENT_KEY}=await load('packages/util/launch-environment/lib/index.js');
const {installModelSelection}=await load('packages/core/agent/lib/index.js');
const {createUserMessage}=await load('packages/llm/llm/lib/index.js');
const patches=JSON.parse(fs.readFileSync(overlay,'utf8'));
patches.push(...['headless-startup','headless-runner'].map(id=>({id,disabled:true})));
const ctx=await boot('chapter3-attempt',path.join(root,'boot.yml'),patches,c=>{
  c.provide(DSH_LAUNCH_ENVIRONMENT_KEY,loadLayeredEnv('chapter3-attempt'));
},pathToFileURL(path.join(runtime,'apps/cli/package.json')).href);
try {
  ctx.on('session/event',(session,event)=>{
    fs.appendFileSync(path.join(root,'native_events.jsonl'),JSON.stringify({session_id:session.id,event})+'\n');
  });
  const selection=ctx.get('agentDefaultModel').currentSelection();
  const {agent}=await ctx.get('agents').create({sessionId:'c3-'+randomUUID(),meta:{cwd:path.join(root,'workspace')},
    agentOptions:{provider:selection.provider,model:selection.model},
    setup:c=>{installModelSelection(c,{current:selection,assembled:undefined});}});
  await agent.whenIdle();
  agent.followup(createUserMessage({content:[{type:'text',text:fs.readFileSync(promptFile,'utf8')}],source:{kind:'user'}}));
  await agent.whenIdle();await ctx.get('sessions').flush(agent.session);
  const events=[];for(let i=0;i<agent.session.seq;i++){const e=agent.session.eventAt(i);if(e)events.push(e);}
  const ended=events.filter(e=>e.type==='turn/end').at(-1);
  const outcome={session_id:agent.session.id,reason:ended?.data?.reason,events:events.length,simulation_success:'not_assessed'};
  fs.writeFileSync(path.join(root,'native_outcome.json'),JSON.stringify(outcome,null,2),{flag:'wx'});
  console.log(JSON.stringify(outcome));
  if(ended?.data?.reason?.kind!=='completed')process.exitCode=1;
} finally {await ctx.fiber.dispose();}
