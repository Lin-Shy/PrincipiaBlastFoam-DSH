// Read-only accounting through DSH's public llm/stream waterfall.
// Includes agent, title and compaction calls, and failed/abandoned streams.
import {appendFileSync} from 'node:fs';
import {randomUUID} from 'node:crypto';
export const name='principia-native-usage-meter';
export const inject=['llm'];

export async function* metered(stream,options,record,callId=randomUUID()) {
 const started=Date.now();let terminal=false,finishKind=null,errorName=null,lastUsage=null;
 const identity={call_id:callId,purpose:options.purpose??'agent',
   provider:options.provider??null,model:options.model??null,
   max_tokens:options.maxTokens??null,session_id:options.sessionId??null};
 record({kind:'llm_call_start',...identity,time:started});
 try {
  for await(const chunk of stream) {
   if(chunk.type==='usage') {
    lastUsage=Object.fromEntries(Object.entries(chunk.usage??{}).filter(([,v])=>typeof v==='number'&&Number.isFinite(v)));
    record({kind:'llm_call_usage',...identity,time:Date.now(),usage:lastUsage});
   }
   if(chunk.type==='finish'){terminal=true;finishKind=chunk.reason?.kind??null;}
   yield chunk;
  }
 } catch(error) {errorName=error?.name??'Error';throw error;}
 finally {record({kind:'llm_call_end',...identity,time:Date.now(),seconds:(Date.now()-started)/1000,
   terminal_observed:terminal,finish_kind:finishKind,error_name:errorName,usage:lastUsage,
   usage_scope:lastUsage?'Last normalized usage emitted by the provider adapter.':'No provider usage observed; billing is unknown, not zero.'});}
}

export function apply(ctx,config={}) {
 if(!config.trace)throw new Error('native usage meter requires an external trace path');
 const record=row=>{try{appendFileSync(config.trace,JSON.stringify(row)+'\n');}catch{process.stderr.write('native usage accounting unavailable\n');}};
 ctx.on('llm/stream',(options,next)=>metered(next(),options,record));
}
