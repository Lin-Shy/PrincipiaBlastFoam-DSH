import fs from 'node:fs';
import path from 'node:path';
import {execFileSync} from 'node:child_process';
import {pathToFileURL} from 'node:url';
const {defineTool}=await import(pathToFileURL(path.join(process.env.C3_RUNTIME,'packages/core/tools/lib/index.js')).href);
export const name='engineering-time-series';
export const inject=['tools'];
export function apply(ctx){
  ctx.tools.register(defineTool({
    name:'pressure_window',description:'Export auditable engineering pressure-window metrics to a new JSON file in the current workspace.',
    parameters:Object.fromEntries(['input','output','ambient','start','end'].map((k,i)=>[k,{type:i<2?'string':'number',required:true,description:k}])),
    output:{schema:{type:'object',additionalProperties:false,properties:{file:{type:'string',required:true},status:{type:'string',required:true}}},render:(_args,value)=>[{type:'text',text:JSON.stringify(value)}]},
    async execute(a){
      const root=fs.realpathSync(process.cwd());
      const input=fs.realpathSync(path.resolve(root,a.input));
      const output=path.resolve(root,a.output);
      if(!input.startsWith(root+path.sep)||fs.realpathSync(path.dirname(output))!==root||fs.existsSync(output))throw Error('Use a workspace input and a new top-level output');
      execFileSync(process.env.C3_PYTHON,['-B',path.join(process.env.C3_MODULE_PATH,'professional','observe.py'),input,'--ambient-pa',String(a.ambient),'--start',String(a.start),'--end',String(a.end),'--output',output],{env:{...process.env,PYTHONPATH:process.env.C3_MODULE_PATH},timeout:60000});
      return {file:path.basename(output),status:JSON.parse(fs.readFileSync(output,'utf8')).status};
    }
  }));
}
