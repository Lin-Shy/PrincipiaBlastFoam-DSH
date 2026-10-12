import {appendFileSync,readFileSync,existsSync} from 'node:fs';
import {createHash} from 'node:crypto';
const original=globalThis.fetch;
const hash=s=>createHash('sha256').update(s).digest('hex');
const content=m=>typeof m.content==='string'?m.content:Array.isArray(m.content)?m.content.map(x=>x.text??'').join('\n'):'';
globalThis.fetch=function(input,init){
 try{
  if(typeof init?.body==='string'&&process.env.PRINCIPIA_REQUEST_METADATA){
   const body=JSON.parse(init.body);
   if(body.model&&Array.isArray(body.messages)){
    const path=process.env.PRINCIPIA_PREFLIGHT_TRACE;const rows=path&&existsSync(path)?readFileSync(path,'utf8').trim().split('\n').filter(Boolean).map(JSON.parse):[];
    const task=process.env.PRINCIPIA_TASK_FILE?readFileSync(process.env.PRINCIPIA_TASK_FILE,'utf8'):'';
    const contexts=body.messages.map((m,index)=>({m,index,text:content(m)})).filter(x=>x.m.role==='user'&&x.text.includes('来源：原始任务绑定的模板检索。'));
    appendFileSync(process.env.PRINCIPIA_REQUEST_METADATA,JSON.stringify({time:Date.now(),model:body.model,reasoning_effort:body.reasoning_effort??null,max_tokens:body.max_tokens??null,
     serialized_request_characters:init.body.length,serialized_messages_characters:JSON.stringify(body.messages).length,
     serialized_request_bytes:Buffer.byteLength(init.body,'utf8'),
     serialized_tool_schema_characters:JSON.stringify(body.tools??[]).length,
     tool_names:(body.tools??[]).map(t=>t.function?.name??t.name).filter(Boolean),
     task_present:body.messages.some(m=>m.role==='user'&&content(m)===task),tool_messages:body.messages.filter(m=>m.role==='tool').length,
     contexts:contexts.map(x=>({index:x.index,characters:x.text.length,sha256:hash(x.text),matches:rows.filter(r=>r.packet).map(r=>({request_sha256:r.request_sha256,packet_characters:JSON.stringify(r.packet).length,packet_contained:x.text.includes(JSON.stringify(r.packet))}))}))})+'\n');
   }
  }
 }catch{}
 return Reflect.apply(original,this,[input,init]);
};
