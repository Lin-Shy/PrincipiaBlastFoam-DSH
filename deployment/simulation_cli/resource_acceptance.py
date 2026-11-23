"""Normal MCP acceptance of the raised local resource ceilings."""
import asyncio,json,os,resource,time,hashlib
from pathlib import Path
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client
WS=Path('/data/chapter3-agent-development/workspace')
APP=WS/'graduation-projects/PrincipiaBlastFoam-DSH'
ROOT=WS/'maintenance/simulation-cli-resource-limits-20261123'
OUT={}
def save(): (ROOT/'mcp-results.json').write_text(json.dumps(OUT,indent=2))
async def call(s,name,**kwargs):
 r=await s.call_tool(name,kwargs)
 return r.structuredContent or json.loads(r.content[0].text)
async def done(s,task):
 for _ in range(500):
  t=await call(s,'status',task_id=task)
  if t['state'] in {'completed','failed','cancelled','timed_out','unknown'}:return t
  await asyncio.sleep(.1)
 raise RuntimeError('Task wait limit')
async def main():
 env={**os.environ,'PRINCIPIA_CASE_ROOT':str(ROOT/'cases'),'SIMULATION_CLI_STATE':str(ROOT/'tasks'),
 'SIMULATION_CLI_HPC_CONFIG':str(WS/'maintenance/simulation-cli-acceptance-20261123/hpc-config.json')}
 params=StdioServerParameters(command=str(WS/'.venv/bin/python'),args=['-m','mcp_servers.simulation_cli.server'],cwd=str(APP),env=env)
 async with stdio_client(params) as (r,w):
  async with ClientSession(r,w) as s:
   await s.initialize()
   OUT['capabilities']=await call(s,'status')
   assert {k:OUT['capabilities']['local'][k] for k in ('cpus','memory_mib','max_seconds')}=={'cpus':4,'memory_mib':4096,'max_seconds':180}
   mesh=await call(s,'execute',command='blockMesh',args=[],case_path='cavity',
    resources={'cpus':4,'memory_mib':4096},timeout_seconds=180,location='local',request_id='raised-limits-mesh')
   assert mesh.get('task_id'),mesh
   OUT['mesh']=await done(s,mesh['task_id']);save()
   assert OUT['mesh']['state']=='completed',OUT['mesh']
   run=await call(s,'execute',command='icoFoam',args=[],case_path=OUT['mesh']['result_path'],
    resources={'cpus':4,'memory_mib':4096,'short_test':True},timeout_seconds=180,location='local',request_id='raised-limits-solver')
   assert run.get('task_id'),run
   for _ in range(200):
    state=await call(s,'status',task_id=run['task_id'])
    if state['state']=='running':break
    assert state['state']=='queued',state
    await asyncio.sleep(.05)
   pid=state['command_pid']
   # Allow wrapper exec to reach the real pinned solver.
   await asyncio.sleep(.5)
   OUT['observed_process']={'pid':pid,'cpu_affinity':sorted(os.sched_getaffinity(pid)),
    'address_space':resource.prlimit(pid,resource.RLIMIT_AS),'cpu_seconds':resource.prlimit(pid,resource.RLIMIT_CPU),
    'thread_environment':{k:v for k,v in (x.split('=',1) for x in Path(f'/proc/{pid}/environ').read_bytes().decode().split('\0') if '=' in x)
       if k in {'OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS'}}}
   assert len(OUT['observed_process']['cpu_affinity'])==4
   assert OUT['observed_process']['address_space']==(4294967296,4294967296)
   assert OUT['observed_process']['cpu_seconds']==(720,720)
   assert set(OUT['observed_process']['thread_environment'].values())=={'4'}
   OUT['before']=state;save()
   while time.time()-state['started_unix']<32:
    await asyncio.sleep(1)
    current=await call(s,'status',task_id=run['task_id'])
    assert current['state']=='running',current
   OUT['after_old_timeout']=current;save()
   OUT['cancel']=await call(s,'cancel',task_id=run['task_id'])
   OUT['terminal']=await done(s,run['task_id'])
   OUT['logs']=await call(s,'logs',task_id=run['task_id'],max_bytes=4096)
   save()
   assert OUT['terminal']['state']=='cancelled',OUT['terminal']
   OUT['over_limits']=[]
   for resources,seconds in [({'cpus':5},180),({'memory_mib':4097},180),({},181)]:
    rejected=await call(s,'execute',command='blockMesh',args=[],case_path='cavity',resources=resources,
      timeout_seconds=seconds,location='local',dry_run=True)
    OUT['over_limits'].append(rejected)
    assert rejected.get('category')=='resource_insufficient',rejected
   OUT['source_sha256']=hashlib.sha256((APP/'src/principia_core/simulation_cli.py').read_bytes()).hexdigest()
   save()
   print(json.dumps({'mesh':OUT['mesh']['state'],'affinity':OUT['observed_process']['cpu_affinity'],
    'address_space_bytes':OUT['observed_process']['address_space'][0],
    'cpu_seconds':OUT['observed_process']['cpu_seconds'][0],
    'wall_seconds_observed':round(time.time()-state['started_unix'],2),
    'terminal':OUT['terminal']['state'],'excess_requests_rejected':len(OUT['over_limits'])}),flush=True)
asyncio.run(main())
