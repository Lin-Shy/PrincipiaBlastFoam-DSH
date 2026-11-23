"""Verify the deployed Web MCP composition without model calls."""
import asyncio,json,os,shutil,hashlib
from pathlib import Path
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client
WS=Path('/data/chapter3-agent-development/workspace')
ROOT=WS/'maintenance/simulation-cli-acceptance-20261123'
WEB=WS/'services/chapter3-web-20261123'
OUT={}
async def call(s,name,**args):
 r=await s.call_tool(name,args);return r.structuredContent or json.loads(r.content[0].text)
async def wait(s,task):
 for _ in range(600):
  state=await call(s,'status',task_id=task)
  if state['state'] in {'completed','failed','cancelled','unknown','timed_out'}:return state
  await asyncio.sleep(.1)
 raise RuntimeError('wait timed out')
async def main():
 inserts=json.loads((WEB/'web.patch.yml').read_text())[-1]['insert']
 for row in inserts:
  if row['id'] not in {'simulation-cli-mcp','principia-domain-mcp'}:continue
  cfg=row['config']
  server=StdioServerParameters(command=cfg['command'],args=cfg['args'],cwd=cfg['cwd'],env={**os.environ,**cfg['env']})
  async with stdio_client(server) as (r,w):
   async with ClientSession(r,w) as s:
    await s.initialize();names=[t.name for t in (await s.list_tools()).tools];OUT[row['id']]=names
    if row['id']=='principia-domain-mcp':
     assert 'mesh_case' not in names and 'run_case' not in names
     continue
    assert set(names)=={'execute','status','logs','cancel'}
    case=WEB/'workspace/cases/simulation-cli-web-maintenance'
    if not case.exists():shutil.copytree(ROOT/'cases/solver100',case)
    task=await call(s,'execute',command='blockMesh',args=[],case_path=str(case),request_id='web-config-live-mesh')
    state=await wait(s,task['task_id']);OUT['mesh']=state
    assert state['state']=='completed',state
    OUT['mesh_logs']=await call(s,'logs',task_id=task['task_id'],max_bytes=8192)
    OUT['missing_mpi']=await call(s,'execute',command='mpirun',args=['-np','2','icoFoam'],case_path=str(case),resources={'cpus':2},dry_run=True)
    OUT['missing_local_tool']=await call(s,'execute',command='blastFoam',args=[],case_path=str(case),location='local',resources={'short_test':True},dry_run=True)
    # Same maintenance grant, different service state directory: still no second job.
    scriptcase=WEB/'workspace/cases/simulation-cli-web-hpc-limit'
    if not scriptcase.exists():shutil.copytree(ROOT/'cases/hpc',scriptcase)
    sha=hashlib.sha256((scriptcase/'Allrun').read_bytes()).hexdigest()
    OUT['exhausted_hpc_grant']=await call(s,'execute',command='Allrun',args=[],case_path=str(scriptcase),resources={'reviewed_script_sha256':sha},timeout_seconds=300,location='hpc',request_id='web-grant-must-refuse-second')
    assert OUT['exhausted_hpc_grant']['category']=='prohibited',OUT['exhausted_hpc_grant']
    # Initialization, decomposition and visualization use actual small local commands.
    initialized=await call(s,'execute',command='setFields',args=[],case_path=state['result_path'],request_id='web-live-setfields')
    initialized=await wait(s,initialized['task_id']);OUT['setFields']=initialized
    assert initialized['state']=='completed',initialized
    case2=WEB/'workspace/cases/simulation-cli-web-decomposition'
    if not case2.exists():
     shutil.copytree(initialized['result_path'],case2)
     (case2/'system/decomposeParDict').write_text('FoamFile { version 2.0; format ascii; class dictionary; object decomposeParDict; }\nnumberOfSubdomains 2; method simple; simpleCoeffs { n (2 1 1); delta 0.001; }\n')
    d=await call(s,'execute',command='decomposePar',args=[],case_path=str(case2),request_id='web-live-decompose')
    OUT['decomposePar']=await wait(s,d['task_id'])
    assert OUT['decomposePar']['state']=='completed',OUT['decomposePar']
    vtk=await call(s,'execute',command='foamToVTK',args=[],case_path=initialized['result_path'],request_id='web-live-vtk')
    OUT['foamToVTK']=await wait(s,vtk['task_id'])
    assert OUT['foamToVTK']['state']=='completed',OUT['foamToVTK']
 (ROOT/'web-mcp-verification.json').write_text(json.dumps(OUT,indent=2))
 print(json.dumps({'tools':OUT['simulation-cli-mcp'],'local_states':{k:OUT[k]['state'] for k in ['mesh','setFields','decomposePar','foamToVTK']},
 'mpi':OUT['missing_mpi']['category'],'missing_tool':OUT['missing_local_tool']['category'],'second_hpc':OUT['exhausted_hpc_grant']['category']}))
asyncio.run(main())
