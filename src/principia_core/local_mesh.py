"""Bounded local mesh operations, separate from solver and HPC execution."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import subprocess
import tempfile
import time

MAX_CELLS = 100_000
MAX_INPUT_BYTES = 32 * 1024 * 1024
MAX_OUTPUT_BYTES = 128 * 1024 * 1024
MAX_SECONDS = 30
MAX_MEMORY_BYTES = 1024 * 1024 * 1024
MESH_FILES = {"points", "faces", "owner", "neighbour", "boundary", "cellZones", "faceZones", "pointZones"}

def _plain(text: str) -> str:
    text = re.sub(r"/\*.*?\*/|//[^\n]*", "", text, flags=re.S)
    if re.search(r"[#$]|\b(?:libs|functions|coded\w*|codeStream|systemCall|geometry)\b", text):
        raise ValueError("Local mesh input must not contain directives, dynamic code, libraries or external geometry")
    return text

def _input(path: Path, case: Path) -> bytes:
    if any(p.is_symlink() for p in [path, *path.parents] if p == case or case in p.parents):
        raise ValueError("Symlink mesh inputs are not supported")
    if not path.is_file() or path.stat().st_size > MAX_INPUT_BYTES:
        raise ValueError("Missing or oversized mesh input")
    raw = path.read_bytes()
    text = raw.decode("ascii")
    if re.search(r"\bformat\s+binary\s*;", text):
        raise ValueError("Local mesh operations require ASCII input")
    _plain(text)
    return raw

def estimate_cells(text: str) -> int:
    text = _plain(text)
    blocks = re.findall(r"\bhex\s*\([^)]*\)\s*(?:[A-Za-z_]\w*\s*)?\(\s*(\d+)\s+(\d+)\s+(\d+)\s*\)", text)
    if not blocks or len(blocks) != len(re.findall(r"\bhex\b", text)):
        raise ValueError("Only explicit hex block cell counts are supported locally")
    total = 0
    for dims in blocks:
        x, y, z = map(int, dims)
        if min(x, y, z) < 1:
            raise ValueError("Mesh dimensions must be positive")
        total += x*y*z
    if total > MAX_CELLS:
        raise ValueError(f"Mesh has {total} cells; local cap is {MAX_CELLS}. Use the HPC workflow")
    return total

def _mesh_cells(owner: str, neighbour: str = "") -> int:
    text = _plain(owner)
    # The labelList payload follows the FoamFile dictionary.
    match = re.search(r"}\s*\d+\s*\((.*?)\)\s*;?\s*$", text, re.S)
    if not match or not re.fullmatch(r"[\d\s]*", match[1]):
        raise ValueError("Unsupported owner labelList")
    labels = [int(x) for x in match[1].split()]
    if neighbour:
        other = re.search(r"}\s*\d+\s*\((.*?)\)\s*;?\s*$", _plain(neighbour), re.S)
        if not other or not re.fullmatch(r"[\d\s]*", other[1]):
            raise ValueError("Unsupported neighbour labelList")
        labels.extend(int(x) for x in other[1].split())
    cells = max(labels, default=-1) + 1
    if not 0 < cells <= MAX_CELLS:
        raise ValueError("Mesh exceeds local cell cap or is empty; use HPC")
    return cells

def local_mesh_status() -> dict:
    root = os.environ.get("PRINCIPIA_LOCAL_MESH_BIN", "")
    enabled = os.environ.get("PRINCIPIA_LOCAL_MESH_ENABLED", "false").lower() == "true"
    available = bool(root) and all((Path(root)/name).is_file() and os.access(Path(root)/name, os.X_OK)
                                  for name in ("blockMesh", "checkMesh"))
    return {"enabled": enabled, "available": available, "operations": ["blockMesh", "checkMesh"],
            "max_cells": MAX_CELLS, "wall_seconds": MAX_SECONDS,
            "memory_bytes": MAX_MEMORY_BYTES, "output_bytes": MAX_OUTPUT_BYTES,
            "cpu_count": 1, "full_solver": "hpc-only", "is_os_sandbox": False}

def run_local_mesh(case_path: Path, operation: str) -> dict:
    if operation not in ("blockMesh", "checkMesh"):
        raise ValueError("Only blockMesh and checkMesh are supported; solvers use HPC")
    status = local_mesh_status()
    if not status["enabled"] or not status["available"]:
        raise ValueError("Local mesh tools are disabled or unavailable")
    case = Path(case_path)
    if case.is_symlink() or not case.is_dir():
        raise ValueError("Expected an existing real case directory")
    case = case.resolve()
    if shutil.disk_usage(case).free < 2 * MAX_OUTPUT_BYTES:
        raise ValueError("Insufficient local disk headroom")
    mem = dict(re.findall(r"^(\w+):\s+(\d+)", Path("/proc/meminfo").read_text(), re.M))
    if int(mem.get("MemAvailable", 0))*1024 < 2*MAX_MEMORY_BYTES:
        raise ValueError("Insufficient available memory; use HPC or wait")
    inputs = {}
    if operation == "blockMesh":
        raw = _input(case/"system/blockMeshDict", case)
        cells = estimate_cells(raw.decode("ascii"))
        inputs["system/blockMeshDict"] = raw
        if (case/"constant").is_symlink() or (case/"constant/polyMesh").exists():
            raise ValueError("Existing polyMesh is not overwritten; use a new case directory")
    else:
        mesh = case/"constant/polyMesh"
        if mesh.is_symlink() or not mesh.is_dir():
            raise ValueError("Expected a real polyMesh directory")
        for p in mesh.iterdir():
            if p.name not in MESH_FILES:
                raise ValueError("Unsupported polyMesh member")
            inputs["constant/polyMesh/"+p.name] = _input(p, case)
        if not {"constant/polyMesh/"+n for n in ("points","faces","owner","neighbour","boundary")} <= inputs.keys():
            raise ValueError("Incomplete polyMesh")
        cells = _mesh_cells(inputs["constant/polyMesh/owner"].decode("ascii"),
                            inputs["constant/polyMesh/neighbour"].decode("ascii"))
    if sum(map(len, inputs.values())) > MAX_INPUT_BYTES:
        raise ValueError("Total mesh input too large; use HPC")
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix=".local-mesh-", dir=case) as temp:
        stage = Path(temp)
        for name, raw in inputs.items():
            target = stage/name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        (stage/"system").mkdir(exist_ok=True)
        (stage/"system/controlDict").write_text(
            "FoamFile { version 2.0; format ascii; class dictionary; object controlDict; }\n"
            "application blockMesh; startFrom startTime; startTime 0; stopAt endTime; endTime 0;\n"
            "deltaT 1; writeControl timeStep; writeInterval 1; writeFormat ascii; runTimeModifiable false;\n")
        # checkMesh constructs fvMesh and requires these dictionaries even without a solver.
        (stage/"system/fvSchemes").write_text(
            "FoamFile { version 2.0; format ascii; class dictionary; object fvSchemes; }\n"
            "ddtSchemes { default steadyState; } gradSchemes { default Gauss linear; }\n"
            "divSchemes { default none; } laplacianSchemes { default Gauss linear corrected; }\n"
            "interpolationSchemes { default linear; } snGradSchemes { default corrected; }\n")
        (stage/"system/fvSolution").write_text(
            "FoamFile { version 2.0; format ascii; class dictionary; object fvSolution; }\nsolvers {}\n")
        binary = str(Path(os.environ["PRINCIPIA_LOCAL_MESH_BIN"])/operation)
        cpu = str(min(os.sched_getaffinity(0)))
        command = ["/usr/bin/prlimit", f"--as={MAX_MEMORY_BYTES}", f"--cpu={MAX_SECONDS}",
                   "--fsize=67108864", "--", "/usr/bin/taskset", "-c", cpu,
                   binary, "-case", str(stage), "-noFunctionObjects"]
        env = {k: v for k, v in os.environ.items()
               if not any(x in k.upper() for x in ("KEY","TOKEN","SECRET","PASSWORD"))}
        env.update(OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1", FOAM_FILEHANDLER="uncollated",
                   FOAM_CODE_STREAM_SECURITY="0")
        log = stage/"operation.log"
        with log.open("wb") as output:
            child = subprocess.Popen(command, env=env, stdout=output, stderr=subprocess.STDOUT,
                                     start_new_session=True)
            failure = None
            try:
                while child.poll() is None:
                    size = sum(p.stat().st_size for p in stage.rglob("*") if p.is_file())
                    if time.monotonic()-started > MAX_SECONDS or size > MAX_OUTPUT_BYTES:
                        failure = "local time/output limit exceeded"
                        os.killpg(child.pid, signal.SIGKILL)
                        break
                    time.sleep(.1)
                child.wait(timeout=5)
            finally:
                if child.poll() is None:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait()
        rawlog = log.read_bytes()
        text = rawlog[-65536:].decode("utf-8", errors="replace")
        valid = child.returncode == 0 and not failure
        if operation == "checkMesh":
            valid = valid and "Mesh OK." in text
        if not valid and failure is None:
            failure = f"{operation} failed: exit={child.returncode}, mesh quality acceptance not met"
        produced = stage/"constant/polyMesh"
        if operation == "blockMesh":
            valid = valid and all((produced/n).is_file() for n in ("points","faces","owner","neighbour","boundary"))
        evidence = case/"local-mesh-evidence"
        evidence.mkdir(exist_ok=True)
        if evidence.is_symlink():
            raise ValueError("Evidence directory must not be a symlink")
        tag = operation+"-"+str(time.time_ns())
        (evidence/(tag+".log")).write_text(text)
        result = {"operation":operation, "execution_host":socket.gethostname(), "execution_location":"independent-linux-local",
                  "scheduler_job":None, "estimated_cells":cells, "exit_code":child.returncode,
                  "passed":valid, "failure":failure, "elapsed_seconds":round(time.monotonic()-started,3),
                  "input_sha256":{n:hashlib.sha256(b).hexdigest() for n,b in inputs.items()},
                  "log":str(evidence/(tag+".log")), "log_sha256":hashlib.sha256(text.encode()).hexdigest(),
                  "limits":status, "output_sha256":{}}
        if valid and operation == "blockMesh":
            for p in produced.iterdir():
                if p.is_symlink() or not p.is_file():
                    raise ValueError("Unexpected mesh output")
                result["output_sha256"][p.name] = hashlib.sha256(p.read_bytes()).hexdigest()
            (case/"constant").mkdir(exist_ok=True)
            if (case/"constant").is_symlink() or (case/"constant/polyMesh").exists():
                raise ValueError("Mesh destination changed during execution")
            produced.rename(case/"constant/polyMesh")
        (evidence/(tag+".json")).write_text(json.dumps(result,indent=2))
        return result
