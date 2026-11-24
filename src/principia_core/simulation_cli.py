"""Persistent simulation-only command execution; not an OS sandbox."""
from __future__ import annotations
import fcntl, hashlib, json, math, os, re, shlex, shutil, signal, socket, subprocess, sys, tarfile, time, uuid
from contextlib import contextmanager
from pathlib import Path
from principia_core.local_mesh import estimate_cells, _mesh_cells
APP=Path(__file__).resolve().parents[2]
DESCRIPTION=("专门执行和管理仿真相关命令行操作，包括网格生成与检查、网格转换、初始化、分解、短时测试、求解、重构及后处理。"
"执行仿真命令时优先使用本服务。服务根据命令、算例规模、软件环境和资源需求，选择独立 Linux 本地执行或通过超算调度执行，并提供状态查询、日志和结果路径。"
"非仿真操作使用其他工具。本服务不负责研究规划或自动改变算例的物理参数、数值方法与实验条件。无法执行时返回明确原因及处理建议。")
COMMANDS={
"blockMesh":"mesh","checkMesh":"check","foamDictionary":"check","snappyHexMesh":"mesh","surfaceFeatureExtract":"mesh",
"gmshToFoam":"convert","fluentMeshToFoam":"convert","ideasUnvToFoam":"convert",
"setFields":"initialize","setRefinedFields":"initialize","initializeAtmosphere":"initialize",
"mapFields":"initialize","potentialFoam":"initialize","topoSet":"initialize",
"decomposePar":"decompose","reconstructPar":"reconstruct","reconstructParMesh":"reconstruct",
"renumberMesh":"mesh","transformPoints":"mesh","createPatch":"mesh",
"icoFoam":"solver","simpleFoam":"solver","pimpleFoam":"solver","rhoCentralFoam":"solver",
"blastFoam":"solver","blastEulerFoam":"solver","blastXiFoam":"solver",
"blastReactingFoam":"solver","blastParcelFoam":"solver","blastFSIFoam":"solver",
"postProcess":"postprocess","foamToVTK":"postprocess","Allrun":"script","mpirun":"parallel"}
TERMINAL={"completed","failed","cancelled","timed_out"}
INPUT_CAP=32*1024*1024
OUTPUT_CAP=128*1024*1024
DEFAULT_CPUS = 2
DEFAULT_MEMORY_MIB = 2048
DEFAULT_TIMEOUT_SECONDS = 60
LOCAL_MAX_CPUS = 4
LOCAL_MAX_MEMORY_MIB = 4096
LOCAL_MAX_SECONDS = 180
LOCAL_MEMORY_RESERVE_BYTES = 512 * 1024 * 1024
DEFAULT_OPENFOAM_ENV = "/data/OpenFOAM/env.sh"
_OPENFOAM_DISCOVERY_CACHE: dict[tuple[str, int, int], dict] = {}

def discover_local_openfoam(env_script: Path) -> dict:
    """Discover Foundation OpenFOAM / blastFoam executables via external env script."""
    resolved = Path(env_script).expanduser()
    if not resolved.is_file():
        return {
            "available": False,
            "env_script": str(resolved),
            "foam_appbin": "",
            "foam_user_appbin": "",
            "version": "",
            "commands": {},
        }
    try:
        st = resolved.stat()
        cache_key = (str(resolved), st.st_mtime_ns, st.st_size)
    except OSError:
        cache_key = (str(resolved), -1, -1)
    cached = _OPENFOAM_DISCOVERY_CACHE.get(cache_key)
    if cached is not None:
        return cached

    probe = (
        'source "$1" >/dev/null 2>&1 || exit 1\n'
        'printf "%s\\n%s\\n%s\\n" "${FOAM_USER_APPBIN:-}" "${FOAM_APPBIN:-}" "${WM_PROJECT_VERSION:-}"'
    )
    try:
        proc = subprocess.run(
            ["/bin/bash", "--noprofile", "--norc", "-c", probe, "simulation-cli-probe", str(resolved)],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return {"available": False, "env_script": str(resolved), "foam_appbin": "", "foam_user_appbin": "", "version": "", "commands": {}}
    if proc.returncode != 0:
        return {"available": False, "env_script": str(resolved), "foam_appbin": "", "foam_user_appbin": "", "version": "", "commands": {}}
    lines = proc.stdout.splitlines()
    foam_user_appbin = lines[0].strip() if len(lines) > 0 else ""
    foam_appbin = lines[1].strip() if len(lines) > 1 else ""
    version = lines[2].strip() if len(lines) > 2 else ""
    discovered: dict[str, str] = {}
    for directory_str in (foam_user_appbin, foam_appbin):
        if not directory_str:
            continue
        bin_dir = Path(directory_str)
        if not bin_dir.is_dir():
            continue
        for name in COMMANDS:
            if name in {"Allrun", "mpirun"} or name in discovered:
                continue
            candidate = bin_dir / name
            if candidate.is_file() and os.access(candidate, os.X_OK):
                discovered[name] = str(candidate)
    result = {
        "available": bool(discovered),
        "env_script": str(resolved),
        "foam_appbin": foam_appbin,
        "foam_user_appbin": foam_user_appbin,
        "version": version,
        "commands": discovered,
    }
    _OPENFOAM_DISCOVERY_CACHE[cache_key] = result
    return result

def _local_software_label(rt: dict) -> str:
    """Format local software string from discovered OpenFOAM metadata."""
    if not rt.get("available"):
        return "OpenFOAM env not configured"
    version = rt.get("version") or "unknown"
    base = f"Foundation OpenFOAM-{version}"
    return f"{base} + blastFoam" if "blastFoam" in rt.get("commands", {}) else base

def local_process_limits(plan):
    """Translate requested resources into enforced affinity and per-process limits."""
    cpus = plan["resources"].get("cpus", DEFAULT_CPUS)
    memory_mib = plan["resources"].get("memory_mib", DEFAULT_MEMORY_MIB)
    seconds = plan["timeout_seconds"]
    if not 1 <= cpus <= LOCAL_MAX_CPUS or not 1 <= memory_mib <= LOCAL_MAX_MEMORY_MIB:
        reject("resource_insufficient", "Local CPU or memory request exceeds deployment limits.")
    if not 1 <= seconds <= LOCAL_MAX_SECONDS:
        reject("resource_insufficient", "Local wall-time request exceeds deployment limit.")
    available_cpus = sorted(os.sched_getaffinity(0))
    if len(available_cpus) < cpus:
        reject("resource_insufficient", "Requested CPU affinity is no longer available.")
    match = re.search(r"^MemAvailable:\s+(\d+)", Path("/proc/meminfo").read_text(), re.M)
    available_memory = int(match[1]) * 1024 if match else 0
    if available_memory < memory_mib * 1048576 + LOCAL_MEMORY_RESERVE_BYTES:
        reject("resource_insufficient", "Insufficient memory plus 512 MiB system reserve at worker start.")
    return dict(cpu_affinity=available_cpus[:cpus], address_space_bytes=memory_mib * 1048576,
                cpu_seconds=seconds * cpus, wall_seconds=seconds, threads=cpus)

def hpc_ulimit_f_blocks(cfg: dict) -> int:
    """Convert max_file_mib into 512-byte POSIX blocks for batch ulimit -f (default 128 MiB -> 262144)."""
    max_mib = cfg.get("max_file_mib", 128)
    if type(max_mib) is not int or max_mib < 1:
        reject("unsupported", "max_file_mib must be a positive integer.")
    return max_mib * 2048

def build_hpc_command_argv(plan: dict, cfg: dict) -> list[str]:
    """Build HPC execution argv with configurable MPI launcher (mpirun or C-cluster srun_pmix)."""
    cmd = plan["command"]
    args = plan["args"]
    if cmd == "Allrun":
        return ["bash", "Allrun"]
    if cmd == "mpirun":
        if len(args) < 3 or args[0] != "-np" or not str(args[1]).isdigit() or int(args[1]) < 2:
            reject("unsupported", "MPI syntax: -np N simulationCommand [args], N >= 2.")
        launcher = cfg.get("mpi_launcher", "mpirun")
        ranks, target, extra = str(args[1]), args[2], args[3:]
        if launcher == "srun_pmix":
            tail = list(extra) if "-parallel" in extra else [*extra, "-parallel"]
            return ["/usr/bin/srun", "--nodes=1", f"--ntasks={ranks}", "--mpi=pmix", target, *tail]
        if launcher == "mpirun":
            return ["mpirun", *args]
        reject("unsupported", f"Unknown HPC mpi_launcher: {launcher}")
    return [cmd, *args]

class Problem(Exception):
    def __init__(self,category,reason,suggestion="Inspect status() capabilities and task evidence."):
        self.data=dict(ok=False,category=category,reason=reason,suggestion=suggestion)
        super().__init__(reason)
def reject(category,reason,suggestion="Inspect status() capabilities and task evidence."):raise Problem(category,reason,suggestion)
def read(p):return json.loads(Path(p).read_text())
def write(p,value):
    p=Path(p);tmp=p.with_name(p.name+"."+uuid.uuid4().hex+".tmp")
    tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n");tmp.replace(p)
def digest(p):
    h=hashlib.sha256()
    with Path(p).open("rb") as stream:
        for part in iter(lambda:stream.read(1048576),b""):h.update(part)
    return h.hexdigest()
def pid_identity(pid):
    try:
        fields=Path(f"/proc/{pid}/stat").read_text().rsplit(")",1)[1].split()
        return None if fields[0]=="Z" else fields[19]
    except (OSError,IndexError):return None
def inventory(case):
    files={};size=0
    for p in case.rglob("*"):
        if p.is_symlink():reject("unsupported","Symlink case members require a separately prepared case.")
        if p.is_file():
            size+=p.stat().st_size
            if size>INPUT_CAP:reject("resource_insufficient","Input exceeds deployed 32 MiB inspection/transfer cap.","Use separately provisioned cluster-native input; no automatic bulk upload.")
            files[p.relative_to(case).as_posix()]=digest(p)
    if not files:reject("unsupported","Empty case directory.")
    return files,size
def cell_count(case):
    try:
        if (case/"constant/polyMesh/owner").exists():
            return _mesh_cells((case/"constant/polyMesh/owner").read_text(),(case/"constant/polyMesh/neighbour").read_text())
        return estimate_cells((case/"system/blockMeshDict").read_text())
    except (OSError,ValueError,UnicodeError):return None

class SimulationCLI:
    def __init__(self):
        self.root=Path(os.getenv("SIMULATION_CLI_STATE",str(APP/"outputs/simulation-cli"))).resolve()
        self.root.mkdir(parents=True,exist_ok=True)
        self.case_root=Path(os.getenv("PRINCIPIA_CASE_ROOT",str(APP/"outputs"))).resolve()
        self.openfoam_env=Path(os.getenv("SIMULATION_CLI_OPENFOAM_ENV",DEFAULT_OPENFOAM_ENV)).expanduser().resolve()
        binding=os.getenv("SIMULATION_CLI_HPC_CONFIG")
        self.config=read(binding) if binding else None
    @contextmanager
    def lock(self):
        with (self.root/"registry.lock").open("a") as f:
            fcntl.flock(f,fcntl.LOCK_EX);yield
    def task(self,task_id):
        if not re.fullmatch(r"sim-[0-9a-f]{24}",task_id):reject("prohibited","Invalid task ID.")
        p=self.root/task_id/"task.json"
        if not p.is_file():reject("unsupported","Unknown task ID.")
        return p,read(p)
    def capabilities(self):
        rt=discover_local_openfoam(self.openfoam_env)
        return dict(ok=True,description=DESCRIPTION,commands=COMMANDS,
          local=dict(software=_local_software_label(rt),
            env_script=str(self.openfoam_env),
            available_commands=[n for n in COMMANDS if n in rt["commands"]],
            max_cells=100000,max_seconds=LOCAL_MAX_SECONDS,memory_mib=LOCAL_MAX_MEMORY_MIB,
            cpus=LOCAL_MAX_CPUS,output_bytes=OUTPUT_CAP,
            memory_reserve_bytes=LOCAL_MEMORY_RESERVE_BYTES,
            defaults=dict(cpus=DEFAULT_CPUS,memory_mib=DEFAULT_MEMORY_MIB,timeout_seconds=DEFAULT_TIMEOUT_SECONDS)),
          hpc=dict(configured=bool(self.config),software="Foundation 9 / separately bound blastFoam",
            grant=self.config.get("grant",{}) if self.config else None,
            available_commands=self.config.get("available_commands",[]) if self.config else [],
            mpi_enabled=bool(self.config and self.config.get("mpi_verified")),
            mpi_launcher=self.config.get("mpi_launcher","mpirun") if self.config else "mpirun",
            max_file_mib=self.config.get("max_file_mib",128) if self.config else 128),
          boundaries=["No arbitrary shell expressions. General shell remains available outside this service; no bypass prevention.",
            "Allrun: HPC only, inspected case-local script with reviewed_script_sha256; no Allclean.",
            "mpirun -np N command requires verified MPI binding; disabled in current deployment.",
            "Stage external argument inputs inside case. Local commands run on snapshots; chain via returned result_path.",
            "No physical/numerical settings are rewritten. Local and HPC share Foundation OpenFOAM-9 / blastFoam family; per-deployment binaries depend on runtime bindings.",
            "Conservative rules, no learned estimator. Unknown scale routes to HPC.",
            "Input cap 32 MiB; remote existing-case attachment and automatic full result download not supported."])
    def plan(self,command,args,case_path,resources,timeout_seconds,location):
        if command not in COMMANDS:reject("unsupported","Command outside deployed simulation capability list.")
        if location not in {"auto","local","hpc"}:reject("unsupported","location must be auto/local/hpc")
        if type(timeout_seconds)!=int or not 1<=timeout_seconds<=3600:reject("unsupported","timeout_seconds must be 1..3600")
        if not isinstance(args,list) or len(args)>128 or any(not isinstance(a,str) or len(a)>4096 or "\x00" in a or "\n" in a for a in args):
            reject("unsupported","args must be a bounded string list")
        if set(resources)-{"cpus","memory_mib","expected_seconds","short_test","reviewed_script_sha256"}:
            reject("unsupported","Unknown resource key.")
        for key in ("cpus","memory_mib","expected_seconds"):
            if key in resources and (type(resources[key])!=int or resources[key]<1):reject("unsupported","Positive integer required: "+key)
        if "short_test" in resources and type(resources["short_test"])!=bool:reject("unsupported","short_test must be boolean")
        raw=Path(case_path)
        case=(self.case_root/raw if not raw.is_absolute() else raw).resolve()
        # Snapshots within the service state may be chained, but arbitrary unrelated paths are rejected.
        if case in {self.case_root,self.root} or not (case.is_relative_to(self.case_root) or case.is_relative_to(self.root)) or not case.is_dir():
            reject("prohibited","Expected existing case below configured case root or task snapshot root.")
        if any(a in {"-case","--case","-parallel","-roots","-hostRoots"} or a.startswith(("-case=","--case=")) for a in args):
            reject("unsupported","Use case_path/mpirun instead of alternate case or parallel switches.")
        if any(a.startswith(("/", "../")) or "/../" in a for a in args):
            reject("unsupported","External argument paths must be staged inside the case.")
        hashes,size=inventory(case);effective=command
        if command=="mpirun":
            if len(args)<3 or args[0]!="-np" or not args[1].isdigit() or int(args[1])<2 or args[2] not in COMMANDS or args[2] in {"Allrun","mpirun"}:
                reject("unsupported","MPI syntax: -np N simulationCommand [args], N >= 2.")
            if resources.get("cpus",int(args[1]))!=int(args[1]):reject("unsupported","MPI ranks must equal cpus.")
            resources={**resources,"cpus":int(args[1])};effective=args[2]
        if command=="Allrun":
            script=case/"Allrun"
            if args:reject("unsupported","Allrun arguments unsupported.")
            if not script.is_file() or resources.get("reviewed_script_sha256")!=digest(script):
                reject("prohibited","Allrun requires matching reviewed_script_sha256.","Inspect all commands, physics and dependencies, then bind the script hash.")
            if re.search(r"\bAllclean\b",script.read_text()):reject("prohibited","Allclean unsupported.")
        resources = {"cpus": DEFAULT_CPUS, "memory_mib": DEFAULT_MEMORY_MIB, **resources}
        cells=cell_count(case);cpus=resources.get("cpus",DEFAULT_CPUS);memory=resources.get("memory_mib",DEFAULT_MEMORY_MIB)
        reasons=[]
        if cells is None:reasons.append("unknown or above-cap mesh size")
        if command in {"Allrun","mpirun"}:reasons.append("script/MPI requires scheduler")
        if (timeout_seconds > LOCAL_MAX_SECONDS or cpus > LOCAL_MAX_CPUS
                or memory > LOCAL_MAX_MEMORY_MIB
                or resources.get("expected_seconds", timeout_seconds) > LOCAL_MAX_SECONDS):
            reasons.append("requested resources exceed local bounds")
        if COMMANDS[effective]=="solver" and not resources.get("short_test"):reasons.append("local solver requires explicit bounded short_test")
        rt=discover_local_openfoam(self.openfoam_env)
        available=effective in rt["commands"]
        if not available:reasons.append("local executable missing")
        free=shutil.disk_usage(case).free
        match=re.search(r"^MemAvailable:\s+(\d+)",Path("/proc/meminfo").read_text(),re.M)
        mem=int(match[1])*1024 if match else 0
        if free < 2 * OUTPUT_CAP or mem < memory * 1048576 + LOCAL_MEMORY_RESERVE_BYTES:
            reasons.append("insufficient current disk/memory headroom; memory requires 512 MiB reserve")
        if cpus > len(os.sched_getaffinity(0)):
            reasons.append("requested CPUs exceed current process affinity")
        if location=="local" and reasons:reject("environment_missing" if not available else "resource_insufficient","; ".join(reasons),"Use auto/hpc with a scoped runtime binding.")
        chosen="hpc" if reasons or location=="hpc" else "local"
        if chosen=="hpc":
            if not self.config or not self.config.get("live_enabled"):reject("environment_missing","HPC environment not configured/enabled.")
            if command=="mpirun" and not self.config.get("mpi_verified"):reject("environment_missing","MPI launcher/ABI not verified in deployment.")
            grant=self.config.get("grant",{})
            if not grant.get("enabled"):reject("prohibited","No current simulation_cli submission grant.")
            if cpus>grant.get("max_cpus",0) or memory>grant.get("max_memory_mib",0) or timeout_seconds>grant.get("max_seconds",0):
                reject("resource_insufficient","Requested resources exceed HPC maintenance grant.")
            if command != "Allrun" and effective not in self.config.get("available_commands",[]):reject("environment_missing","Command missing from bound HPC runtime: "+effective)
        return dict(command=command,args=args,case_path=str(case),resources=resources,timeout_seconds=timeout_seconds,location=chosen,
            estimated_cells=cells,input_bytes=size,input_sha256=hashes,routing_reasons=reasons or ["within local bounds; executable/headroom available"],
            estimate="conservative rules; runtime uncalibrated; no learned estimator",software=_local_software_label(rt) if chosen=="local" else "Foundation 9 / bound blastFoam",
            available_disk_bytes=free,available_memory_bytes=mem)
    def execute(self,command,args,case_path,resources=None,timeout_seconds=DEFAULT_TIMEOUT_SECONDS,location="auto",dry_run=False,request_id=None):
        resources=resources or {}
        request=dict(command=command,args=args,case_path=case_path,resources=resources,timeout_seconds=timeout_seconds,location=location)
        identity=json.dumps(request,sort_keys=True);key=request_id or hashlib.sha256(identity.encode()).hexdigest()
        if not isinstance(key,str) or len(key)>256:reject("unsupported","request_id max length 256.")
        task_id="sim-"+hashlib.sha256(key.encode()).hexdigest()[:24]
        with self.lock():
            p=self.root/task_id/"task.json"
            if p.exists():
                t=read(p)
                if t["request"]!=request:reject("prohibited","request_id bound to different request.")
                return {**self.status(task_id),"duplicate":True}
            plan=self.plan(command,args,case_path,resources,timeout_seconds,location)
            if dry_run:return dict(ok=True,dry_run=True,plan=plan)
            for other in self.root.glob("sim-*/task.json"):
                old=read(other)
                if old["plan"]["case_path"]==plan["case_path"] and old["state"] not in TERMINAL:
                    reject("prohibited","Case has active/unknown task: "+old["task_id"],"Query/reconcile/cancel before new execution.")
            if plan["location"]=="hpc":
                used=sum(1 for _ in Path(self.config["grant"]["ledger_path"]).glob("sim-*.json"))
                if used>=self.config["grant"].get("max_submissions",0):reject("prohibited","Scoped HPC submission allowance exhausted.")
            folder=p.parent;folder.mkdir()
            t=dict(ok=True,task_id=task_id,request=request,plan=plan,state="queued",created_unix=time.time(),execution_host=socket.gethostname(),
                result_path=str(folder/"case") if plan["location"]=="local" else None,exit_code=None,log_path=str(folder/"execution.log"))
            write(p,t)
            try:
                with (folder/"worker.log").open("ab") as output:
                    child=subprocess.Popen([sys.executable,"-m","principia_core.simulation_cli",str(self.root),task_id],
                        stdin=subprocess.DEVNULL,stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
            except OSError as error:
                t.update(state="failed",error=dict(type=type(error).__name__,reason="Worker launch failed: "+str(error)))
                write(p,t)
                return t
            t.update(worker_pid=child.pid,worker_start=pid_identity(child.pid));write(p,t);(folder/"go").touch()
            return dict(ok=True,task_id=task_id,state="queued",plan=plan)
    def status(self,task_id=None):
        if task_id is None:return self.capabilities()
        p,t=self.task(task_id)
        if t["plan"]["location"]=="hpc" and t["state"]=="unknown" and not t.get("job_id") and t.get("run_id"):
            t=HPC(self,p.parent).reconcile(t)
            write(p,t)
        if t["plan"]["location"]=="hpc" and t.get("job_id"):
            t=HPC(self,p.parent).status(t);write(p,t)
        elif t["state"] not in TERMINAL and t.get("worker_pid") and pid_identity(t["worker_pid"])!=t.get("worker_start"):
            latest=read(p)
            if latest["state"] in TERMINAL:return latest
            t.update(state="unknown",error="Worker lost; inspect evidence before retry.")
            if t["plan"]["location"]=="hpc" and t.get("run_id"):
                t=HPC(self,p.parent).reconcile(t)
                if t.get("job_id"):t=HPC(self,p.parent).status(t)
                write(p,t)
        return t
    def logs(self,task_id,max_bytes=16384):
        if type(max_bytes)!=int or not 1<=max_bytes<=65536:reject("unsupported","max_bytes must be 1..65536")
        p,t=self.task(task_id)
        if t["plan"]["location"]=="hpc" and t.get("job_id"):return HPC(self,p.parent).logs(t,max_bytes)
        log=p.parent/"execution.log"
        if not log.exists():log=p.parent/"worker.log"
        with log.open("rb") as f:
            size=log.stat().st_size;f.seek(max(0,size-max_bytes));raw=f.read(max_bytes)
        return dict(ok=True,task_id=task_id,text=raw.decode(errors="replace"),truncated=size>max_bytes,result_path=t["result_path"])
    def cancel(self,task_id):
        p,t=self.task(task_id);(p.parent/"cancel-requested").touch()
        if t.get("command_pid") and pid_identity(t["command_pid"])==t.get("command_start"):
            try:os.killpg(t["command_pid"],signal.SIGKILL)
            except ProcessLookupError:pass
            if pid_identity(t.get("worker_pid",0))!=t.get("worker_start"):
                t.update(state="cancelled",error="Orphaned owned command terminated by recorded process identity.");write(p,t)
        if t["state"] in TERMINAL:return t
        if t["plan"]["location"]=="hpc" and t.get("job_id"):return HPC(self,p.parent).cancel(t)
        return dict(ok=True,task_id=task_id,state="cancel_requested",detail="Worker will acknowledge; query status.")

class HPC:
    def __init__(self,service,folder):
        self.service=service;self.folder=folder
        binding=folder/"hpc-binding.json"
        self.cfg=read(binding) if binding.exists() else dict(service.config)
        if not binding.exists():write(binding,self.cfg)
        sys.path.insert(0,str(APP/"experiments/end2end"));sys.path.insert(0,str(APP/"deployment/remote"))
        import cluster_job
        from linux_scheduler_bridge import guarded_plan
        self.core=cluster_job;self.guarded_plan=guarded_plan
    def ssh(self,command,timeout=45):
        return self.core.ssh(self.cfg,command,capture_output=True,text=True,timeout=timeout).stdout
    def submit(self,t):
        plan=t["plan"]
        self.cfg.update(tasks=plan["resources"].get("cpus",DEFAULT_CPUS),wall_minutes=math.ceil(plan["timeout_seconds"]/60),memory_mib=plan["resources"].get("memory_mib",DEFAULT_MEMORY_MIB))
        run_id="c3-"+t["task_id"];spec=self.guarded_plan(self.core,self.cfg,run_id);remote=spec["remote"]
        t.update(remote=remote,result_path=remote+"/payload/case",run_id=run_id,state="staging");write(self.folder/"task.json",t)
        ledger=Path(self.cfg["grant"]["ledger_path"]);ledger.mkdir(parents=True,exist_ok=True)
        with (ledger/"allowance.lock").open("a") as allowance:
            fcntl.flock(allowance,fcntl.LOCK_EX)
            used=sum(1 for _ in ledger.glob("sim-*.json"))
            if used>=self.cfg["grant"]["max_submissions"]:reject("prohibited","Submission allowance consumed by another task.")
            intent=dict(run_id=run_id,remote=remote,plan=plan)
            write(ledger/(t["task_id"]+".json"),intent)
            write(self.folder/"hpc-submit-intent.json",intent)
        payload=self.folder/"payload";shutil.copytree(plan["case_path"],payload/"case")
        if inventory(payload/"case")[0]!=plan["input_sha256"]:reject("prohibited","Input changed while staging.")
        argv=build_hpc_command_argv(plan,self.cfg)
        script="set -euo pipefail\ncd payload/case\n"+shlex.join(["timeout","--signal=TERM","--kill-after=5",str(plan["timeout_seconds"]),*argv])+"\n"
        (payload/"run_case.sh").write_text(script)
        batch=spec["batch_script"].replace('node=$(hostname -s)','printf "%s\\n" "$record" > logs/scheduler-allocation.txt\nnode=$(hostname -s)')
        batch=batch.replace("bash payload/run_case.sh",f"ulimit -f {hpc_ulimit_f_blocks(self.cfg)}\nbash payload/run_case.sh")
        (self.folder/"batch.sh").write_text(batch)
        archive=self.folder/"payload.tar"
        with tarfile.open(archive,"x") as tar:
            for p in payload.rglob("*"):
                if p.is_file():tar.add(p,arcname="payload/"+p.relative_to(payload).as_posix(),recursive=False)
        q=shlex.quote(remote)
        self.ssh('umask 077; test "$(id -u)" = 15505 && mkdir '+q+' && mkdir '+q+'/logs '+q+'/tmp '+q+'/home')
        subprocess.run(["scp","-q","-F",self.cfg["ssh_config"],str(archive),str(self.folder/"batch.sh"),self.cfg["ssh_target"]+":"+remote+"/"],check=True,timeout=90)
        if self.ssh("cd "+q+" && sha256sum payload.tar").split()[0]!=digest(archive):raise RuntimeError("payload transfer hash mismatch")
        self.ssh("cd "+q+" && tar -xf payload.tar")
        if (self.folder/"cancel-requested").exists():t["state"]="cancelled";return t
        t["state"]="submitting";write(self.folder/"task.json",t)
        out=self.ssh(shlex.join(spec["submit_argv"]))
        (self.folder/"submit.stdout").write_text(out)
        match=re.search(r"Submitted batch job\s+(\d+)",out)
        if not match:raise RuntimeError("Ambiguous submission; reconcile run_id, never auto-resubmit.")
        t.update(job_id=match[1],state="submitted",payload_sha256=digest(archive))
        write(self.folder/"job_receipt.json",dict(job_id=match[1],remote=remote,run_id=run_id))
        write(self.folder/"task.json",t)
        shutil.rmtree(payload);archive.unlink()
        if (self.folder/"cancel-requested").exists():self.cancel(t)
        return t
    def reconcile(self,t):
        # Read-only recovery of an ambiguous submit. Never create a replacement job.
        start=time.strftime("%Y-%m-%d",time.localtime(t["created_unix"]-86400))
        raw=self.ssh("sacct -u sysu_pww_2 --name "+shlex.quote(t["run_id"])+" -S "+start+
                     " -n -P --format=JobIDRaw,JobName%64,User")
        matches=[]
        for line in raw.splitlines():
            fields=line.split("|")
            if len(fields)>=3 and fields[0].isdigit() and fields[1]==t["run_id"] and fields[2]=="sysu_pww_2":
                matches.append(fields[0])
        matches=sorted(set(matches))
        if len(matches)==1:
            t.update(job_id=matches[0],state="submitted",reconciled=True)
            write(self.folder/"job_receipt.json",dict(job_id=matches[0],remote=t["remote"],run_id=t["run_id"]))
        else:t["reconciliation"]="No unique owned scheduler job found; no automatic retry."
        return t
    def owned(self,t):
        receipt=read(self.folder/"job_receipt.json")
        if any(receipt[k]!=t[k] for k in ("job_id","remote","run_id")) or not str(t["job_id"]).isdigit():
            reject("prohibited","Owned job receipt mismatch.")
        return str(t["job_id"])
    def status(self,t):
        job=self.owned(t)
        raw=self.ssh("sacct -j "+job+" -n -P --format=JobID,JobName%64,State,ExitCode,NodeList,Elapsed,AllocCPUS")
        t["accounting"]=raw[:16384]
        for line in raw.splitlines():
            parts=line.split("|")
            if parts[0]==job and len(parts)>=7:
                if parts[1]!=t["run_id"]:reject("prohibited","Scheduler job name differs from receipt.")
                state=parts[2].split()[0];t.update(scheduler_state=state,scheduler_exit=parts[3],allocated_nodes=parts[4],elapsed=parts[5])
                if state=="COMPLETED":t.update(state="completed" if parts[3]=="0:0" else "failed",exit_code=int(parts[3].split(":")[0]))
                elif state.startswith("CANCELLED"):t["state"]="cancelled"
                elif state=="TIMEOUT":t["state"]="timed_out"
                elif state in {"FAILED","NODE_FAIL","OUT_OF_MEMORY","PREEMPTED","BOOT_FAIL"}:t["state"]="failed"
                else:t["state"]="running" if state=="RUNNING" else "submitted"
        return t
    def logs(self,t,maximum):
        self.owned(t)
        command="cd "+shlex.quote(t["remote"])+" && { for p in logs/allocated_host.txt logs/scheduler-allocation.txt logs/pipeline.exit logs/pipeline.stderr logs/pipeline.stdout; do if test -f \"$p\"; then printf '\\n%s\\n' \"$p\"; tail -c "+str(maximum)+" \"$p\"; fi; done; } | tail -c "+str(maximum)
        raw=self.ssh(command)
        return dict(ok=True,task_id=t["task_id"],text=raw,max_bytes=maximum,result_path=t["result_path"])
    def cancel(self,t):
        job=self.owned(t);record=self.ssh("scontrol show job -o "+job)
        if "JobName="+t["run_id"]+" " not in record or not re.search(r"UserId=\S+\(15505\)",record):
            reject("prohibited","Cancellation requires scheduler owner and job-name match.")
        self.ssh("scancel "+job)
        return dict(ok=True,task_id=t["task_id"],state="cancel_requested",job_id=job)

def worker(root,task_id):
    os.environ["SIMULATION_CLI_STATE"]=root
    service=SimulationCLI();p,t=service.task(task_id);folder=p.parent
    for _ in range(100):
        if (folder/"go").exists():break
        time.sleep(.02)
    else:return
    try:
        if (folder/"cancel-requested").exists():t["state"]="cancelled";write(p,t);return
        if t["plan"]["location"]=="hpc":
            t=HPC(service,folder).submit(t);write(p,t);return
        plan=t["plan"];case=folder/"case";shutil.copytree(plan["case_path"],case)
        if inventory(case)[0]!=plan["input_sha256"]:reject("prohibited","Input changed while staging.")
        rt=discover_local_openfoam(service.openfoam_env)
        exe=rt["commands"].get(plan["command"])
        if not exe:reject("environment_missing","Local executable missing for command: "+plan["command"])
        argv=[exe,*plan["args"]]
        shell="source "+shlex.quote(str(service.openfoam_env))+'\nexec "$@"'
        limits = local_process_limits(plan)
        cpu = ",".join(str(number) for number in limits["cpu_affinity"])
        argv=["/usr/bin/prlimit","--as="+str(limits["address_space_bytes"]),
              "--cpu="+str(limits["cpu_seconds"]),"--fsize=67108864","--",
              "/usr/bin/taskset","-c",cpu,"/bin/bash","--noprofile","--norc","-c",shell,"simulation-cli",*argv]
        env={k:v for k,v in os.environ.items() if not any(x in k.upper() for x in ("KEY","TOKEN","SECRET","PASSWORD"))}
        threads = str(limits["threads"])
        env.update(OMP_NUM_THREADS=threads,OPENBLAS_NUM_THREADS=threads,MKL_NUM_THREADS=threads)
        if (folder/"cancel-requested").exists():t["state"]="cancelled";write(p,t);return
        with (folder/"execution.log").open("wb") as output:
            child=subprocess.Popen(argv,cwd=case,env=env,stdout=output,stderr=subprocess.STDOUT,start_new_session=True)
            t.update(state="running",command_pid=child.pid,command_start=pid_identity(child.pid),started_unix=time.time(),enforced_resources=limits);write(p,t)
            reason=None
            while child.poll() is None:
                if (folder/"cancel-requested").exists():reason="cancelled"
                elif time.time()-t["started_unix"]>plan["timeout_seconds"]:reason="timed_out"
                elif sum(x.stat().st_size for x in folder.rglob("*") if x.is_file())>OUTPUT_CAP:reason="failed"
                if reason:
                    os.killpg(child.pid,signal.SIGKILL);break
                time.sleep(.05)
            code=child.wait()
            if (folder/"cancel-requested").exists():reason="cancelled"
        outputs={x.relative_to(case).as_posix():digest(x) for x in case.rglob("*") if x.is_file() and not x.is_symlink()}
        t.update(state=reason or ("completed" if code==0 else "failed"),exit_code=code,finished_unix=time.time(),output_sha256=outputs,
            log_sha256=digest(folder/"execution.log"))
        if plan["command"]=="checkMesh":
            with (folder/"execution.log").open("rb") as stream:
                stream.seek(max(0,(folder/"execution.log").stat().st_size-65536))
                t["mesh_ok"]="Mesh OK." in stream.read().decode(errors="replace")
            if not t["mesh_ok"] and t["state"]=="completed":t["state"]="failed"
        write(p,t)
    except Exception as error:
        t.update(state="unknown" if (folder/"hpc-submit-intent.json").exists() and not t.get("job_id") else "failed",
            error=error.data if isinstance(error,Problem) else dict(type=type(error).__name__,reason=str(error)[:2048]))
        write(p,t)
if __name__=="__main__":worker(sys.argv[1],sys.argv[2])
