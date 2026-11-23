import fs from 'node:fs';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {createHash,randomUUID} from 'node:crypto';
import assert from 'node:assert/strict';
const [runtime,root,profile,action,tool,params]=process.argv.slice(2);
const load=p=>import(pathToFileURL(path.join(runtime,p)).href);
const {boot,loadLayeredEnv}=await load('packages/boot/app-boot/lib/index.js');
const {DSH_LAUNCH_ENVIRONMENT_KEY:key}=await load('packages/util/launch-environment/lib/index.js');
const patches=['headless-startup','headless-runner'].map(id=>({id,disabled:true}));
console.error('Starting native profile');
const ctx=await boot('c3-engineering',path.join(root,'boot.yml'),patches,c=>{c.provide(key,loadLayeredEnv('c3-engineering'));},pathToFileURL(path.join(runtime,'apps/cli/package.json')).href);
console.error('Native profile activated');
try{
 const tools=ctx.get('tools'),skills=ctx.get('skills'),cwd=process.cwd();
 const log={profile,driver:'direct DSH tool dispatch; no model',skills:(await skills.list({cwd})).map(s=>s.name),tools:[...tools.view().visible.keys()].sort(),calls:[]};
 async function call(name,args){
   const result=await tools.execute({name,arguments:args,callId:randomUUID(),signal:new AbortController().signal});
   log.calls.push({name,args,result});if(result.isError)throw Error(JSON.stringify(result));return result;
 }
 if(action==='invoke')await call(tool,JSON.parse(params));
 if(action==='accept'){
   if(log.tools.includes('pressure_window')!==(profile==='professional'))throw Error('profile mismatch');
   const file='pump.txt',raw=fs.readFileSync(file,'utf8');
   await call('read',{file_path:file});
   await call('write',{file_path:'source-copy.txt',content:raw});
   if(fs.readFileSync('source-copy.txt','utf8')!==raw)throw Error('write mismatch');
   if(profile==='professional'){
     for(const name of ['engineering-delivery','blastfoam-quality-review'])await call('skill',{name});
     await call('pressure_window',{input:file,output:'metrics.json',ambient:100000,start:0,end:2});
     const result=JSON.parse(fs.readFileSync('metrics.json'));const m=result.metrics[0];
     if(result.source_sha256!==createHash('sha256').update(raw).digest('hex')||m.peak_overpressure_pa!==200||m.sampled_peak_time_s!==1||m.whole_window_positive_area_pa_s!==200)throw Error('independent triangle oracle mismatch');
   }
   fs.writeFileSync('acceptance.json',JSON.stringify(log,null,2),{flag:'wx'});
 }
 if(action==='delivery-check'){
   assert(log.tools.includes('verify_artifact_manifest'), 'Pass --delivery-controls');
   fs.writeFileSync('check-input.txt','original\n',{flag:'wx'});
   const hash=createHash('sha256').update('original\n').digest('hex');
   fs.writeFileSync('check-manifest.json',JSON.stringify({files:{'check-input.txt':hash}}),{flag:'wx'});
   const before=fs.readFileSync('check-input.txt');
   const checked=JSON.parse((await call('verify_artifact_manifest',{manifest:'check-manifest.json',directory:'.'})).value.result);
   assert.equal(checked.expected_count,1);assert.equal(checked.matched_count,1);assert.equal(checked.status,'all_matched');
   assert.deepEqual(fs.readFileSync('check-input.txt'),before);
   fs.writeFileSync('check-differences.json',JSON.stringify({files:{'check-input.txt':'0'.repeat(64),'missing.txt':hash}}),{flag:'wx'});
   const differences=JSON.parse((await call('verify_artifact_manifest',{manifest:'check-differences.json',directory:'.'})).value.result);
   assert.equal(differences.expected_count,2);assert.equal(differences.missing_count,1);assert.equal(differences.mismatched_count,1);
   assert(!fs.existsSync('missing.txt'));
   const command="Add-Content -LiteralPath guard-marker.txt -Value x; Write-Output stable";
   for(let i=0;i<3;i++)await call('pwsh',{command,description:'offline repeated action probe'});
   for(let i=0;i<2;i++){
     const args={command,description:'changed label must not bypass guard'};
     const result=await tools.execute({name:'pwsh',arguments:args,callId:randomUUID(),signal:new AbortController().signal});
     log.calls.push({name:'pwsh',args,result});
     assert(result.isError);assert(JSON.stringify(result.content).includes('REPEATED_UNCHANGED_ACTION'));
   }
   assert.equal(fs.readFileSync('guard-marker.txt','utf8').trim().split(/\r?\n/).length,3);
   await call('read',{file_path:'check-input.txt'});
   await call('pwsh',{command,description:'different intervening action allows a fresh check'});
   assert.equal(fs.readFileSync('guard-marker.txt','utf8').trim().split(/\r?\n/).length,4);
   // Same command with changing output must not be classified as unchanged.
   const changing="Add-Content -LiteralPath changing-marker.txt -Value x; (Get-Content changing-marker.txt | Measure-Object -Line).Lines";
   for(let i=0;i<5;i++)await call('pwsh',{command:changing,description:'changing result probe'});
   assert.equal(fs.readFileSync('changing-marker.txt','utf8').trim().split(/\r?\n/).length,5);
   assert.deepEqual(fs.readFileSync('check-input.txt'),before);
   fs.writeFileSync('delivery-controls-acceptance.json',JSON.stringify({...log,passed:true,model_calls:0,node_jobs:0},null,2),{flag:'wx'});
 }
 console.log(JSON.stringify(log));
}finally{await ctx.fiber.dispose();}
