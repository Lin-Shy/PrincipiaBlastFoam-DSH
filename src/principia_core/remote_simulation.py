"""Lightweight asynchronous Linux solver jobs; no agent or retrieval dependency."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tarfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any

TERMINAL = {"completed", "failed", "cancelled", "timed_out", "storage_limited"}
IDENTIFIER = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}\Z")


def identifier(value: str) -> str:
    if not IDENTIFIER.fullmatch(value):
        raise ValueError("Expected a simple case/job ID, not a filesystem path")
    return value


def read(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def tail(path: Path, lines: int = 100) -> str:
    if not path.is_file():
        return ""
    with path.open("rb") as handle:
        handle.seek(max(0, path.stat().st_size - 65536))
        return "\n".join(handle.read(65536).decode("utf-8", errors="replace").splitlines()[-lines:])


class SimulationRunner:
    def __init__(self, root: Path, command: list[str], *, max_jobs: int = 1,
                 min_free_bytes: int = 2 * 1024**3, max_input_bytes: int = 512 * 1024**2):
        self.root = root.expanduser().resolve()
        self.command = command
        self.max_jobs = max_jobs
        self.min_free_bytes = min_free_bytes
        self.max_input_bytes = max_input_bytes
        self.lock = threading.Lock()
        for name in ("incoming", "jobs"):
            (self.root / name).mkdir(parents=True, exist_ok=True)

    def job(self, job_id: str) -> Path:
        path = self.root / "jobs" / identifier(job_id)
        if path.is_symlink() or not path.is_dir():
            raise ValueError("Unknown job")
        return path

    def status(self, job_id: str) -> dict[str, Any]:
        return read(self.job(job_id) / "status.json")

    def submit(self, case_id: str, timeout_seconds: int = 3600) -> dict[str, Any]:
        identifier(case_id)
        if not 1 <= timeout_seconds <= 86400:
            raise ValueError("Timeout must be between 1 and 86400 seconds")
        source = self.root / "incoming" / case_id
        if source.is_symlink() or not source.is_dir():
            raise ValueError("Upload a case directory to incoming/<case_id> first")
        if not (source / "system/controlDict").is_file() or not (source / "Allrun").is_file():
            raise ValueError("Case must contain system/controlDict and Allrun")
        size = 0
        for path in source.rglob("*"):
            if path.is_symlink() or not (path.is_file() or path.is_dir()):
                raise ValueError("Input must contain only ordinary files and directories")
            if path.is_file():
                size += path.stat().st_size
        if size > self.max_input_bytes:
            raise ValueError("Case input exceeds configured limit")
        with self.lock:
            active = [p for p in (self.root / "jobs").glob("*/status.json")
                      if read(p)["state"] not in TERMINAL]
            if len(active) >= self.max_jobs:
                raise RuntimeError("Remote solver capacity is occupied; poll the current job")
            if shutil.disk_usage(self.root).free < self.min_free_bytes + size:
                raise RuntimeError("Insufficient remote free space")
            job_id = uuid.uuid4().hex
            directory = self.root / "jobs" / job_id
            directory.mkdir()
            try:
                shutil.copytree(source, directory / "case")
                save(directory / "request.json", {"command": self.command,
                     "timeout_seconds": timeout_seconds, "min_free_bytes": self.min_free_bytes,
                     "case_id": case_id})
                save(directory / "status.json", {"job_id": job_id, "case_id": case_id,
                     "state": "queued", "submitted_at": time.time(), "exit_code": None})
                # Independent worker survives MCP client disconnects and service restart.
                with (directory / "worker.log").open("ab") as log:
                    subprocess.Popen([sys.executable, str(Path(__file__).resolve()),
                                      "--worker", str(directory)], stdin=subprocess.DEVNULL,
                                     stdout=log, stderr=log, start_new_session=True)
            except Exception:
                shutil.rmtree(directory)
                raise
            # The isolated job owns the snapshot; do not keep duplicate staging data.
            shutil.rmtree(source)
            return {"job_id": job_id, "state": "queued"}

    def logs(self, job_id: str, tail_lines: int = 100) -> dict[str, Any]:
        if not 1 <= tail_lines <= 500:
            raise ValueError("tail_lines must be between 1 and 500")
        directory = self.job(job_id)
        result = {"job_id": job_id, "stdout": tail(directory / "run.log", tail_lines),
                  "worker": tail(directory / "worker.log", tail_lines)}
        result["solver_logs"] = [{"path": str(p.relative_to(directory / "case")),
            "tail": tail(p, min(tail_lines, 50))}
            for p in sorted((directory / "case").rglob("log*")) if p.is_file()][:8]
        return result

    def result(self, job_id: str) -> dict[str, Any]:
        directory = self.job(job_id)
        status = self.status(job_id)
        if status["state"] not in TERMINAL:
            return {**status, "ready": False}
        result = read(directory / "result.json") if (directory / "result.json").is_file() else {}
        return {**status, **result, "ready": bool(result)}

    def cancel(self, job_id: str) -> dict[str, Any]:
        directory = self.job(job_id)
        status = self.status(job_id)
        if status["state"] not in TERMINAL:
            (directory / "cancel").touch()
        return {"job_id": job_id, "cancel_requested": status["state"] not in TERMINAL}

    def cleanup(self, job_id: str, downloaded_sha256: str) -> dict[str, Any]:
        result = self.result(job_id)
        if not result.get("ready") or result.get("archive_sha256") != downloaded_sha256:
            raise ValueError("Cleanup requires a finished job and matching downloaded archive SHA256")
        directory = self.job(job_id)
        for attempt in range(20):
            try:
                shutil.rmtree(directory)
                break
            except PermissionError:
                if os.name != "nt" or attempt == 19:
                    raise
                time.sleep(0.1)  # Worker closes its inherited log just after terminal status.
        return {"job_id": job_id, "removed": True}


def stop(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":  # Test support only; production server is Linux.
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
    else:
        os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            process.kill()
        else:
            os.killpg(process.pid, signal.SIGKILL)
        process.wait()


def worker(directory: Path) -> None:
    request = read(directory / "request.json")
    status = read(directory / "status.json")
    started = time.monotonic()
    status.update(state="running", started_at=time.time(), worker_pid=os.getpid())
    save(directory / "status.json", status)
    process = None
    try:
        with (directory / "run.log").open("wb") as log:
            process = subprocess.Popen([*request["command"], str(directory / "case")],
                cwd=directory / "case", stdout=log, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, start_new_session=True)
            state = "running"
            while process.poll() is None:
                if (directory / "cancel").exists():
                    state = "cancelled"
                elif time.monotonic() - started >= request["timeout_seconds"]:
                    state = "timed_out"
                elif shutil.disk_usage(directory).free < request["min_free_bytes"]:
                    state = "storage_limited"
                if state != "running":
                    stop(process)
                    break
                time.sleep(0.2)
            code = process.wait()
            if state == "running":
                state = "completed" if code == 0 else "failed"
        status.update(exit_code=code)
    except BaseException as error:
        if process is not None:
            stop(process)
        state = "failed"
        status["error"] = f"{type(error).__name__}: {error}"
    try:
        case = directory / "case"
        files = [p for p in case.rglob("*") if p.is_file() and not p.is_symlink()]
        logs = [p for p in files if p.name.startswith("log")]
        log_health = [{"path": str(p.relative_to(case)),
                       "clean_end_in_tail": bool(re.search(r"(?m)^\s*End\s*$", tail(p, 500)))} for p in logs]
        archive = directory / "result.tar.gz"
        # Avoid a second full disk copy; tar streams directly to the compressed archive.
        with tarfile.open(archive, "w:gz", dereference=False) as tar:
            tar.add(directory / "run.log", arcname="run.log", recursive=False)
            for path in files:
                tar.add(path, arcname="case/" + path.relative_to(case).as_posix(), recursive=False)
        save(directory / "result.json", {"archive_path": str(archive), "archive_sha256": digest(archive),
            "archive_bytes": archive.stat().st_size, "file_count": len(files), "solver_logs": log_health,
            "validation": "Process/log evidence only; task, required fields and finite values must be verified locally."})
    except Exception as error:
        state = "failed"
        status["result_error"] = str(error)
    status.update(state=state, finished_at=time.time(), elapsed_seconds=round(time.monotonic() - started, 3))
    save(directory / "status.json", status)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", type=Path, required=True)
    worker(parser.parse_args().worker.resolve())
