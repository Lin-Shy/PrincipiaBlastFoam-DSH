"""One authorized HPC maintenance acceptance via MCP. Re-running uses the same request ID."""
import asyncio,json,os,sys
from pathlib import Path
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client
ROOT=Path('/data/chapter3-agent-development/workspace/maintenance/simulation-cli-acceptance-20261123')
APP=ROOT.parents[1]/'graduation-projects/PrincipiaBlastFoam-DSH'
async def call(s,name,**kwargs):
 r=await s.call_tool(name,kwargs);return r.structuredContent or json.loads(r.content[0].text)
async def main():
 env={**os.environ,'SIMULATION_CLI_STATE':str(ROOT/'tasks'),'PRINCIPIA_CASE_ROOT':str(ROOT/'cases'),'SIMULATION_CLI_HPC_CONFIG':str(ROOT/'hpc-config.json')}
 server=StdioServerParameters(command=str(APP.parents[1]/'.venv/bin/python'),args=['-m','mcp_servers.simulation_cli.server'],cwd=str(APP),env=env)
 async with stdio_client(server) as (r,w):
  async with ClientSession(r,w) as s:
   await s.initialize()
   protocol=json.loads((ROOT/'protocol.json').read_text())
   task=await call(s,'execute',command='Allrun',args=[],case_path='hpc',resources={'reviewed_script_sha256':protocol['allrun_sha256'],'memory_mib':2048},
                   timeout_seconds=300,location='hpc',request_id='unique-hpc-maintenance-20261123')
   (ROOT/'hpc-execute.json').write_text(json.dumps(task,indent=2))
   assert task.get('task_id'),task
   print(json.dumps({'task_id':task['task_id'],'state':task['state'],'duplicate':task.get('duplicate',False)}),flush=True)
   if len(sys.argv)>1 and sys.argv[1]=='submit':return
   state=await call(s,'status',task_id=task['task_id'])
   (ROOT/'hpc-status.json').write_text(json.dumps(state,indent=2))
   print(json.dumps({k:state.get(k) for k in ('state','job_id','remote','scheduler_state','scheduler_exit','allocated_nodes','error')}),flush=True)
   if state.get('job_id'):
    logs=await call(s,'logs',task_id=task['task_id'],max_bytes=65536)
    (ROOT/'hpc-logs.json').write_text(json.dumps(logs,indent=2))
asyncio.run(main())
