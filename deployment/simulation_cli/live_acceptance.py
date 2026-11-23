"""No-model live MCP functional acceptance. Independent maintenance fixtures only."""
import asyncio,json,os,time
from pathlib import Path
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client
ROOT=Path('/data/chapter3-agent-development/workspace/maintenance/simulation-cli-acceptance-20261123')
APP=ROOT.parents[1]/'graduation-projects/PrincipiaBlastFoam-DSH'
ENV={**os.environ,'SIMULATION_CLI_STATE':str(ROOT/'tasks'),'PRINCIPIA_CASE_ROOT':str(ROOT/'cases'),
     'SIMULATION_CLI_HPC_CONFIG':str(ROOT/'hpc-config.json')}
OUT={}
def save(): (ROOT/'mcp-results.json').write_text(json.dumps(OUT,ensure_ascii=False,indent=2,default=str))
async def call(session,name,**kwargs):
    result=await session.call_tool(name,kwargs)
    data=result.structuredContent
    if data is None:data=json.loads(result.content[0].text)
    if isinstance(data,dict) and set(data)=={'result'}:data=data['result']
    return data
async def done(session,task):
    for _ in range(600):
        data=await call(session,'status',task_id=task)
        if data.get('state') in {'completed','failed','cancelled','timed_out','unknown'}:return data
        await asyncio.sleep(.1)
    raise RuntimeError('wait timeout')
async def main():
    server=StdioServerParameters(command=str(APP.parents[1]/'.venv/bin/python'),args=['-m','mcp_servers.simulation_cli.server'],cwd=str(APP),env=ENV)
    async with stdio_client(server) as (r,w):
      async with ClientSession(r,w) as s:
        await s.initialize()
        OUT['tool_names']=[t.name for t in (await s.list_tools()).tools]
        OUT['capabilities']=await call(s,'status')
        mesh=await call(s,'execute',command='blockMesh',args=[],case_path='local',request_id='live-local-mesh')
        OUT['mesh_execute']=mesh;save()
        assert mesh.get('task_id'),mesh
    # Reconnect from a new server process; local worker survives MCP connection shutdown.
    async with stdio_client(server) as (r,w):
      async with ClientSession(r,w) as s:
        await s.initialize()
        OUT['mesh_status']=await done(s,mesh['task_id']);save()
        assert OUT['mesh_status']['state']=='completed',OUT['mesh_status']
        OUT['mesh_logs']=await call(s,'logs',task_id=mesh['task_id'],max_bytes=8192)
        OUT['duplicate']=await call(s,'execute',command='blockMesh',args=[],case_path='local',request_id='live-local-mesh')
        assert OUT['duplicate'].get('duplicate') and OUT['duplicate']['task_id']==mesh['task_id']
        check=await call(s,'execute',command='checkMesh',args=[],case_path=OUT['mesh_status']['result_path'],request_id='live-local-check')
        OUT['check_status']=await done(s,check['task_id']);save()
        assert OUT['check_status']['state']=='completed' and OUT['check_status']['mesh_ok'],OUT['check_status']
        OUT['check_logs']=await call(s,'logs',task_id=check['task_id'],max_bytes=8192)
        sm=await call(s,'execute',command='blockMesh',args=[],case_path='solver100',request_id='live-solver100-mesh')
        sm=await done(s,sm['task_id']);OUT['solver_mesh']=sm
        solver=await call(s,'execute',command='icoFoam',args=[],case_path=sm['result_path'],resources={'short_test':True},request_id='live-local-solver100')
        OUT['solver_status']=await done(s,solver['task_id']);save()
        OUT['solver_logs']=await call(s,'logs',task_id=solver['task_id'],max_bytes=8192);save()
        assert OUT['solver_status']['state']=='completed',OUT['solver_status']
        cm=await call(s,'execute',command='blockMesh',args=[],case_path='cancel',request_id='live-cancel100-mesh')
        cs=await done(s,cm['task_id']);OUT['cancel_mesh']=cs;save()
        assert cs['state']=='completed',cs
        run=await call(s,'execute',command='icoFoam',args=[],case_path=cs['result_path'],resources={'short_test':True},request_id='live-cancel100-solver')
        for _ in range(200):
            state=await call(s,'status',task_id=run['task_id'])
            if state['state']=='running':break
            await asyncio.sleep(.02)
        OUT['cancel_before']=state
        OUT['cancel_request']=await call(s,'cancel',task_id=run['task_id'])
        OUT['cancel_status']=await done(s,run['task_id']);save()
        assert OUT['cancel_status']['state']=='cancelled',OUT['cancel_status']
        OUT['over_limit']=await call(s,'execute',command='blockMesh',args=[],case_path='local',resources={'cpus':2},location='local',dry_run=True)
        OUT['unsupported']=await call(s,'execute',command='git',args=['status'],case_path='local',dry_run=True)
        OUT['missing_mpi']=await call(s,'execute',command='mpirun',args=['-np','2','icoFoam'],case_path='local',resources={'cpus':2},dry_run=True)
        OUT['unreviewed_script']=await call(s,'execute',command='Allrun',args=[],case_path='hpc',dry_run=True)
        OUT['bounded_log']=await call(s,'logs',task_id=mesh['task_id'],max_bytes=100)
        save()
        print(json.dumps({'tools':OUT['tool_names'],'mesh':OUT['mesh_status']['state'],'check':OUT['check_status']['state'],
            'solver':OUT['solver_status']['state'],'cancel':OUT['cancel_status']['state'],'duplicate':OUT['duplicate'].get('duplicate'),
            'over_limit':OUT['over_limit'],'unsupported':OUT['unsupported'],'missing_mpi':OUT['missing_mpi']},ensure_ascii=False))
asyncio.run(main())
