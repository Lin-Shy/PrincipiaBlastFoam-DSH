"""Verify the default request through a real MCP simulation process."""
import asyncio,json,os,resource,hashlib,shutil
from pathlib import Path
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client
WS=Path('/data/chapter3-agent-development/workspace')
APP=WS/'graduation-projects/PrincipiaBlastFoam-DSH'
ROOT=WS/'maintenance/simulation-cli-defaults-20261124'
async def call(s,name,**kwargs):
 r=await s.call_tool(name,kwargs)
 return r.structuredContent or json.loads(r.content[0].text)
async def done(s,task):
 for _ in range(100):
  t=await call(s,'status',task_id=task)
  if t['state'] in {'completed','failed','cancelled','timed_out','unknown'}:return t
  await asyncio.sleep(.1)
 raise RuntimeError('bounded wait expired')
async def main():
 ROOT.mkdir(exist_ok=True);(ROOT/'cases').mkdir(exist_ok=True)
 case=ROOT/'cases/cavity'
 if not case.exists():shutil.copytree(WS/'maintenance/simulation-cli-resource-limits-20261123/cases/cavity',case)
 params=StdioServerParameters(command=str(WS/'.venv/bin/python'),args=['-m','mcp_servers.simulation_cli.server'],cwd=str(APP),
 env={**os.environ,'PRINCIPIA_CASE_ROOT':str(ROOT/'cases'),'SIMULATION_CLI_STATE':str(ROOT/'tasks'),
 'SIMULATION_CLI_HPC_CONFIG':str(WS/'maintenance/simulation-cli-acceptance-20261123/hpc-config.json')})
 out={}
 async with stdio_client(params) as (r,w):
  async with ClientSession(r,w) as s:
   await s.initialize()
   tools=(await s.list_tools()).tools
   out['schema_timeout_default']=next(t for t in tools if t.name=='execute').inputSchema['properties']['timeout_seconds']['default']
   out['capabilities']=await call(s,'status')
   mesh=await call(s,'execute',command='blockMesh',args=[],case_path='cavity',request_id='defaults-20261124-mesh')
   out['mesh']=await done(s,mesh['task_id']);assert out['mesh']['state']=='completed',out['mesh']
   run=await call(s,'execute',command='icoFoam',args=[],case_path=out['mesh']['result_path'],
       resources={'short_test':True},request_id='defaults-20261124-solver')
   for _ in range(100):
    t=await call(s,'status',task_id=run['task_id'])
    if t['state']=='running':break
    assert t['state']=='queued',t
    await asyncio.sleep(.05)
   await asyncio.sleep(.3);pid=t['command_pid']
   out['running']=t
   out['process']={'affinity':sorted(os.sched_getaffinity(pid)),
      'address_space':resource.prlimit(pid,resource.RLIMIT_AS),'cpu_seconds':resource.prlimit(pid,resource.RLIMIT_CPU)}
   assert len(out['process']['affinity'])==2
   assert out['process']['address_space']==(2147483648,2147483648)
   assert out['process']['cpu_seconds']==(120,120)
   assert t['plan']['resources']=={'cpus':2,'memory_mib':2048,'short_test':True}
   assert t['plan']['timeout_seconds']==out['schema_timeout_default']==60
   out['cancel']=await call(s,'cancel',task_id=run['task_id'])
   out['terminal']=await done(s,run['task_id']);assert out['terminal']['state']=='cancelled'
   out['source_sha256']=hashlib.sha256((APP/'src/principia_core/simulation_cli.py').read_bytes()).hexdigest()
   (ROOT/'mcp-results.json').write_text(json.dumps(out,indent=2))
 print(json.dumps({'mesh':out['mesh']['state'],'defaults':out['capabilities']['local']['defaults'],
  'process':out['process'],'terminal':out['terminal']['state']}))
asyncio.run(main())
