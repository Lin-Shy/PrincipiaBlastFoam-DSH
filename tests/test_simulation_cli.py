import json
from pathlib import Path
import pytest
from principia_core.simulation_cli import SimulationCLI,Problem,write
@pytest.fixture
def service(tmp_path,monkeypatch):
    monkeypatch.setenv("SIMULATION_CLI_STATE",str(tmp_path/"state"))
    monkeypatch.setenv("PRINCIPIA_CASE_ROOT",str(tmp_path/"cases"))
    monkeypatch.delenv("SIMULATION_CLI_HPC_CONFIG",raising=False)
    case=tmp_path/"cases/a";(case/"system").mkdir(parents=True)
    (case/"system/blockMeshDict").write_text("hex (0 1 2 3 4 5 6 7) (10 10 10) simpleGrading (1 1 1)")
    return SimulationCLI(),case
def test_capabilities(service):
    s,c=service
    assert s.capabilities()["local"]["max_seconds"]==180
    assert s.capabilities()["local"]["cpus"]==4
    assert s.capabilities()["local"]["memory_mib"]==4096
    assert "Allrun" in s.capabilities()["commands"]
@pytest.mark.parametrize("command,args,category",[
    ("git",[],"unsupported"),("blockMesh",["-case","elsewhere"],"unsupported"),
    ("Allrun",[],"prohibited"),("mpirun",["-np","x","icoFoam"],"unsupported")])
def test_bad_requests(service,command,args,category):
    s,c=service
    with pytest.raises(Problem) as e:s.execute(command,args,str(c),dry_run=True)
    assert e.value.data["category"]==category
def test_large_mesh_local_refused(service):
    s,c=service;(c/"system/blockMeshDict").write_text("hex (0 1 2 3 4 5 6 7) (1000 1000 1000)")
    with pytest.raises(Problem) as e:s.execute("blockMesh",[],str(c),location="local",dry_run=True)
    assert e.value.data["category"]=="resource_insufficient"
def test_unknown_routes_hpc(service):
    s,c=service;(c/"system/blockMeshDict").unlink();(c/"system/a").write_text("x")
    with pytest.raises(Problem) as e:s.execute("blockMesh",[],str(c),dry_run=True)
    assert e.value.data["category"]=="environment_missing"
def test_request_id_conflict_before_input_inspection(service):
    s,c=service
    import hashlib
    task_id="sim-"+hashlib.sha256(b"same").hexdigest()[:24]
    folder=s.root/task_id;folder.mkdir()
    write(folder/"task.json",{"request":{},"task_id":task_id})
    with pytest.raises(Problem) as e:s.execute("blockMesh",[],str(c),request_id="same")
    assert e.value.data["category"]=="prohibited"
def test_invalid_task(service):
    s,c=service
    with pytest.raises(Problem):s.status("../../x")
def test_local_solver_needs_explicit_short_test(service):
    s,c=service
    with pytest.raises(Problem) as e:s.execute("icoFoam",[],str(c),location="local",dry_run=True)
    assert e.value.data["category"]=="resource_insufficient"
def test_log_bound(service):
    s,c=service
    with pytest.raises(Problem):s.logs("sim-"+"0"*24,65537)

def test_external_argument_refused(service):
    s,c=service
    with pytest.raises(Problem) as e:s.execute("blockMesh",["-dict","/other/dict"],str(c),dry_run=True)
    assert e.value.data["category"]=="unsupported"

def bind_hpc(s,tmp_path):
    ledger=tmp_path/"allowance";ledger.mkdir()
    s.config={"live_enabled":True,"available_commands":["blockMesh"],"mpi_verified":False,
      "grant":{"enabled":True,"max_cpus":1,"max_memory_mib":2048,"max_seconds":300,"max_submissions":1,"ledger_path":str(ledger)}}
    return ledger

def test_mpi_environment_distinct_from_grant_limits(service,tmp_path):
    s,c=service;bind_hpc(s,tmp_path)
    with pytest.raises(Problem) as e:s.execute("mpirun",["-np","2","icoFoam"],str(c),dry_run=True)
    assert e.value.data["category"]=="environment_missing"

def test_shared_allowance_prevents_second_state_root(service,tmp_path):
    s,c=service;ledger=bind_hpc(s,tmp_path)
    (ledger/"sim-existing.json").write_text("{}")
    s.root=tmp_path/"other-state";s.root.mkdir()
    with pytest.raises(Problem) as e:s.execute("blockMesh",[],str(c),resources={"cpus":1},location="hpc",request_id="second")
    assert e.value.data["category"]=="prohibited"
    assert list(s.root.glob("sim-*"))==[]

def test_reviewed_allrun_hash_must_match(service,tmp_path):
    s,c=service;bind_hpc(s,tmp_path)
    (c/"Allrun").write_text("blockMesh\ncheckMesh\n")
    with pytest.raises(Problem) as e:s.execute("Allrun",[],str(c),resources={"reviewed_script_sha256":"0"*64},dry_run=True)
    assert e.value.data["category"]=="prohibited"

def test_spawn_failure_is_terminal(service,monkeypatch):
    s,c=service
    def fail(*args,**kwargs):raise OSError("fixture launch failure")
    monkeypatch.setattr("principia_core.simulation_cli.subprocess.Popen",fail)
    task=s.execute("blockMesh",[],str(c),request_id="launch-failure")
    assert task["state"]=="failed"
    assert s.status(task["task_id"])["state"]=="failed"

def test_dead_hpc_worker_reconciles_without_resubmitting(service,monkeypatch):
    s,c=service
    task_id="sim-"+"a"*24;folder=s.root/task_id;folder.mkdir()
    write(folder/"task.json",dict(task_id=task_id,plan={"location":"hpc"},state="submitting",
        worker_pid=999999999,worker_start="none",run_id="c3-fixture",created_unix=0))
    calls=[]
    class Recover:
        def __init__(self,*args):pass
        def reconcile(self,t):
            calls.append("read-only-reconcile");return {**t,"job_id":"123","state":"submitted"}
        def status(self,t):return {**t,"state":"completed"}
    monkeypatch.setattr("principia_core.simulation_cli.HPC",Recover)
    assert s.status(task_id)["state"]=="completed"
    assert calls==["read-only-reconcile"]


@pytest.mark.parametrize("resources,seconds", [
    ({"cpus":5},30), ({"memory_mib":4097},30), ({},181),
    ({"expected_seconds":181},180),
])
def test_updated_local_ceiling_rejects_excess(service,resources,seconds):
    s,c=service
    with pytest.raises(Problem) as error:
        s.execute("blockMesh",[],str(c),resources=resources,timeout_seconds=seconds,location="local",dry_run=True)
    assert error.value.data["category"]=="resource_insufficient"

def test_full_local_ceiling_and_enforced_limits(service,monkeypatch):
    import principia_core.simulation_cli as cli
    s,c=service
    monkeypatch.setattr(cli.os,"sched_getaffinity",lambda pid:set(range(8)))
    original=Path.read_text
    def memory(path,*args,**kwargs):
        return "MemAvailable: 6291456 kB" if str(path)=="/proc/meminfo" else original(path,*args,**kwargs)
    monkeypatch.setattr(Path,"read_text",memory)
    plan=s.plan("blockMesh",[],str(c),{"cpus":4,"memory_mib":4096},180,"local")
    limits=cli.local_process_limits(plan)
    assert plan["location"]=="local"
    assert limits==dict(cpu_affinity=[0,1,2,3],address_space_bytes=4294967296,cpu_seconds=720,wall_seconds=180,threads=4)

def test_worker_rechecks_memory_headroom(service,monkeypatch):
    import principia_core.simulation_cli as cli
    monkeypatch.setattr(Path,"read_text",lambda *args,**kwargs:"MemAvailable: 4194304 kB")
    with pytest.raises(Problem,match="512 MiB"):
        cli.local_process_limits({"resources":{"cpus":1,"memory_mib":4096},"timeout_seconds":180})

def test_new_defaults_are_recorded_and_enforced(service):
    import principia_core.simulation_cli as cli
    s,c=service
    result=s.execute("blockMesh",[],str(c),location="local",dry_run=True)
    plan=result["plan"]
    assert plan["resources"]["cpus"]==2
    assert plan["resources"]["memory_mib"]==2048
    assert plan["timeout_seconds"]==60
    limits=cli.local_process_limits(plan)
    assert len(limits["cpu_affinity"])==2
    assert limits["address_space_bytes"]==2147483648
    assert limits["cpu_seconds"]==120
    assert s.capabilities()["local"]["defaults"]==dict(cpus=2,memory_mib=2048,timeout_seconds=60)

def test_partial_resources_preserve_new_defaults(service):
    s,c=service
    plan=s.execute("blockMesh",[],str(c),resources={"cpus":1},dry_run=True)["plan"]
    assert plan["resources"]=={"cpus":1,"memory_mib":2048}

def test_mcp_schema_default_timeout_is_sixty():
    import asyncio
    from mcp_servers.simulation_cli.server import mcp
    tools=asyncio.run(mcp.list_tools())
    execute=next(tool for tool in tools if tool.name=="execute")
    assert execute.inputSchema["properties"]["timeout_seconds"]["default"]==60
