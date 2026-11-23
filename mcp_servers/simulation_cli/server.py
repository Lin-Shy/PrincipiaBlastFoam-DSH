"""Simulation command execution MCP."""
import asyncio,subprocess
from mcp.server.fastmcp import FastMCP
from principia_core.simulation_cli import SimulationCLI,DESCRIPTION,Problem
mcp=FastMCP("simulation_cli",instructions=DESCRIPTION)
def call(method,*args):
    try:return getattr(SimulationCLI(),method)(*args)
    except Problem as e:return e.data
    except (OSError,ValueError,subprocess.SubprocessError) as e:return dict(ok=False,category="environment_missing",reason=str(e),suggestion="Inspect runtime and task evidence; do not blindly resubmit.")
@mcp.tool()
async def execute(command:str,args:list[str],case_path:str,resources:dict|None=None,timeout_seconds:int=30,location:str="auto",dry_run:bool=False,request_id:str|None=None)->dict:
    """Execute/submit simulation command; returns persistent task_id. No mandatory evaluation step.
    args are individual argv strings; case_path is below configured root. No physics/numerical dictionaries rewritten.
    resources: cpus, memory_mib, expected_seconds, short_test. Local ceilings: 4 CPUs, 4096 MiB, 180 seconds.
    Defaults remain 1 CPU, 1024 MiB and 30 seconds; request higher resources explicitly.
    Allrun requires reviewed_script_sha256.
    short_test explicitly permits bounded local solver tests; timeout terminates without editing endTime.
    status() lists actual software/commands/limits/script/MPI boundaries. request_id prevents repeat submissions.
    Local commands use snapshots: chain next command with returned result_path.
    HPC fields remain on cluster; remote existing-case continuation is not yet implemented."""
    return await asyncio.to_thread(call,"execute",command,args,case_path,resources,timeout_seconds,location,dry_run,request_id)
@mcp.tool()
async def status(task_id:str|None=None)->dict:
    """Query task state/exit/location/results after reconnect. Omit ID for capabilities and software versions."""
    return await asyncio.to_thread(call,"status",task_id)
@mcp.tool()
async def logs(task_id:str,max_bytes:int=16384)->dict:
    """Read latest bounded output, 1..65536 bytes. HPC native fields remain on cluster."""
    return await asyncio.to_thread(call,"logs",task_id,max_bytes)
@mcp.tool()
async def cancel(task_id:str)->dict:
    """Request cancellation of this recorded local task or owned scheduler job. Poll status for acknowledgement."""
    return await asyncio.to_thread(call,"cancel",task_id)
if __name__=="__main__":mcp.run(transport="stdio")
