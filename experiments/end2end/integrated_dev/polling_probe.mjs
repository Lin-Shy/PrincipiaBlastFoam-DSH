// Controlled external-state change, dispatched through the real native tools.
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {randomUUID} from 'node:crypto';
import {pathToFileURL} from 'node:url';
const [runtime,root,variant]=process.argv.slice(2);
const load=p=>import(pathToFileURL(path.join(runtime,p)).href);
const {boot,loadLayeredEnv}=await load('packages/boot/app-boot/lib/index.js');
const {DSH_LAUNCH_ENVIRONMENT_KEY:key}=await load('packages/util/launch-environment/lib/index.js');
const ctx=await boot('c3-polling-probe',path.join(root,'boot.yml'),['headless-startup','headless-runner'].map(id=>({id,disabled:true})),c=>{
  c.provide(key,loadLayeredEnv('c3-polling-probe'));
},pathToFileURL(path.join(runtime,'apps/cli/package.json')).href);
try {
  const tools=ctx.get('tools'),calls=[];
  const invoke=async(name,args)=>{
    const result=await tools.execute({name,arguments:args,callId:randomUUID(),signal:new AbortController().signal});
    calls.push({name,args,result});return result;
  };
  fs.writeFileSync('simulated-status.txt','PENDING',{flag:'wx'});
  const args={command:'Get-Content -LiteralPath simulated-status.txt',description:'Poll controlled external state'};
  for(let i=0;i<3;i++){
    const result=await invoke('pwsh',args);
    assert(!result.isError);assert(result.value.stdout.text.includes('PENDING'));
  }
  // Test controller changes state outside the tool call, like an asynchronous job.
  fs.writeFileSync('simulated-status.txt','COMPLETED');
  const afterChange=await invoke('pwsh',args);
  if(variant==='on'){
    assert(afterChange.isError);
    assert(JSON.stringify(afterChange.content).includes('REPEATED_UNCHANGED_ACTION'));
    const read=await invoke('read',{file_path:'simulated-status.txt'});assert(!read.isError);
    const resumed=await invoke('pwsh',args);assert(!resumed.isError);
    assert(resumed.value.stdout.text.includes('COMPLETED'));
  }else{
    assert(!afterChange.isError);assert(afterChange.value.stdout.text.includes('COMPLETED'));
  }
  const record={variant,simulated_external_state:true,model_calls:0,node_jobs:0,
    legitimate_changed_state_poll_blocked:afterChange.isError,
    recovery:variant==='on'?'different read action followed by a new poll':'not needed',
    elapsed_time_alone_is_not_a_reset:true,tool_calls:calls.length,calls};
  fs.writeFileSync('polling-probe.json',JSON.stringify(record,null,2),{flag:'wx'});
  console.log(JSON.stringify({variant,passed:true,blocked:afterChange.isError,tool_calls:calls.length}));
}finally{await ctx.fiber.dispose();}
