"""Final no-model checks of persistent tasks and deployed configuration."""
import asyncio,json,os,time
from pathlib import Path
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client
WS=Path('/data/chapter3-agent-development/workspace')
ROOT=WS/'maintenance/simulation-cli-acceptance-20261123'
APP=WS/'graduation-projects/PrincipiaBlastFoam-DSH'
async def call(s,name,**args):
 r=await s.call_tool(name,args);return r.structuredContent or json.loads(r.content[0].text)
async def main():
 env={**os.environ,'SIMULATION_CLI_STATE':str(ROOT/'tasks'),'PRINCIPIA_CASE_ROOT':str(ROOT/'cases'),'SIMULATION_CLI_HPC_CONFIG':str(ROOT/'hpc-config.json')}
 p=StdioServerParameters(command=str(WS/'.venv/bin/python'),args=['-m','mcp_servers.simulation_cli.server'],cwd=str(APP),env=env)
 async with stdio_client(p) as (r,w):
  async with ClientSession(r,w) as s:
   await s.initialize()
   original=json.loads((ROOT/'mcp-results.json').read_text())
   task=await call(s,'execute',command='icoFoam',args=[],case_path=original['cancel_mesh']['result_path'],
                    resources={'short_test':True},timeout_seconds=1,request_id='final-timeout-one-second')
   for _ in range(100):
    state=await call(s,'status',task_id=task['task_id'])
    if state['state'] in {'timed_out','failed','completed','unknown'}:break
    await asyncio.sleep(.1)
   out={'timeout':state,'logs':await call(s,'logs',task_id=task['task_id'],max_bytes=4096),
        'terminal_hpc_cancel':await call(s,'cancel',task_id='sim-cf639a656cfe3e1f83d8b640')}
   assert state['state']=='timed_out',state
   assert out['terminal_hpc_cancel']['state']=='completed',out
   (ROOT/'final-mcp-checks.json').write_text(json.dumps(out,indent=2))
   print(json.dumps({'timeout':state['state'],'terminal_hpc_cancel':out['terminal_hpc_cancel']['state']}))
asyncio.run(main())
