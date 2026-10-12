// Opt-in priority navigation, contributed through public durable user context.
import {execFile} from 'node:child_process';
import {appendFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {latestUserRequest} from './native_request_context.mjs';
export const name='principia-preflight-context';
export const inject=['agents','systemPrompt'];
const section='principia-task-navigation';
const variable='principia_task_navigation_packet';

export function currentTask(agent){
 let claimed;
 // Claims precede prompt assembly; session persistence follows it.
 agent.ctx.on('agent/inbox/claimed',({message})=>{
  if(message.source?.kind==='user')
   claimed=latestUserRequest([{type:'user/message',data:message}]);
 });
 return ()=>claimed??latestUserRequest(agent.session.snapshotEvents());
}

export function taskCache(load){
 let key=null,pending=null;
 return async(request,signal)=>{
  if(!request)return null;
  const next=createHash('sha256').update(request).digest('hex');
  if(next!==key){
   key=next;
   pending=load(request,signal).catch(error=>{if(key===next){key=null;pending=null;}throw error;});
  }
  return pending;
 };
}

export function attachNavigation(assembly,packet){
 if(!packet||packet.status==='not_applicable')return assembly;
 assembly.variables[variable]='来源：原始任务绑定的模板检索。以下是候选修改与来源，不是实际副本现状或运行通过证明。\n'+JSON.stringify(packet);
 assembly.contexts=assembly.contexts.filter(x=>x.name!==section);
 assembly.contexts.push({name:section,text:'{{'+variable+'}}'});
 return assembly;
}

export function apply(ctx,config={}){
 const record=entry=>{if(config.trace)try{appendFileSync(config.trace,JSON.stringify(entry)+'\n');}catch{process.stderr.write('preflight trace unavailable\n');}};
 ctx.on('agent/created',({agent})=>{
  const requestNow=currentTask(agent);
  const cached=taskCache(async(request,signal)=>{
   const started=Date.now();
   let packet,result='';
   try{
   result=await new Promise((resolve,reject)=>{
    const child=execFile(config.python??process.env.PRINCIPIA_PYTHON??'python3',
     ['-m','experiments.retrieval_method.preflight_navigation'],
     {cwd:config.root??process.env.PRINCIPIA_PROJECT_ROOT??process.cwd(),
      env:{...process.env,...(config.factoryGraph?{PRINCIPIA_FACTORY_GRAPH:config.factoryGraph}:{})},
      signal,timeout:60000,maxBuffer:2*1024*1024},
     (error,stdout)=>error?reject(error):resolve(stdout));
    child.stdin.end(JSON.stringify({original_request:request,budget:5000}));
   });
   packet=JSON.parse(result);
   }catch(error){
    if(signal?.aborted)throw error;
    packet={status:'navigation_unavailable',error_type:error.name};
   }
   record({kind:'automatic_navigation',agent_id:agent.id,
    started_at:started,seconds:(Date.now()-started)/1000,request_sha256:createHash('sha256').update(request).digest('hex'),
    result_characters:result.trimEnd().length,packet});
   return packet;
  });
  agent.ctx.on('system-prompt/assemble',async(assembly,context,next)=>{
   const result=await next();
   const request=requestNow();
   try{
    const packet=await cached(request,context.signal);
    return request===requestNow()?attachNavigation(result,packet):result;
   }
   catch(error){
    if(context.signal?.aborted)throw error;
    record({kind:'automatic_navigation_error',agent_id:agent.id,error_name:error.name});
    return result;
   }
  });
 });
}
