"""Local SFTP file bridge; large case/results stay outside MCP payloads."""
from __future__ import annotations
import hashlib
import os
import shlex
import subprocess
import uuid
from pathlib import Path, PurePosixPath
from mcp.server.fastmcp import FastMCP
from principia_core.remote_simulation import identifier


def call(command: list[str]) -> None:
    result = subprocess.run(command, capture_output=True, text=True, timeout=600)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "SSH/SFTP transfer failed")


def create_server(local_root: Path, remote_root: str, host: str = "yan_yun") -> FastMCP:
    local_root = local_root.expanduser().resolve()
    remote = PurePosixPath(remote_root)
    if not remote.is_absolute() or str(remote) == "/" or ".." in remote.parts:
        raise ValueError("Configure an absolute non-root Linux SIMULATION_ROOT")
    server = FastMCP("principia-simulation-files")

    def local_path(value: str) -> Path:
        path = Path(value).expanduser().resolve()
        if not path.is_relative_to(local_root) or path == local_root:
            raise ValueError("Transfer paths must be inside PRINCIPIA_CASE_ROOT")
        return path

    @server.tool()
    def upload_simulation_case(case_path: str) -> dict:
        """Upload a local case over SFTP; return the case_id accepted by run_simulation."""
        case = local_path(case_path)
        if not case.is_dir() or not (case / "Allrun").is_file() or not (case / "system/controlDict").is_file():
            raise ValueError("A case with Allrun and system/controlDict is required")
        total = 0
        for path in case.rglob("*"):
            if path.is_symlink() or not (path.is_file() or path.is_dir()):
                raise ValueError("Only regular input files/directories can be uploaded")
            if path.is_file():
                total += path.stat().st_size
        if total > 512 * 1024**2:
            raise ValueError("Input exceeds the 512 MiB upload limit")
        case_id = uuid.uuid4().hex
        destination = str(remote / "incoming" / case_id)
        call(["ssh", "-o", "BatchMode=yes", "-o", "ClearAllForwardings=yes", host,
              "mkdir -p -- " + shlex.quote(destination)])
        call(["scp", "-o", "BatchMode=yes", "-o", "ClearAllForwardings=yes", "-r",
              case.as_posix() + "/.", host + ":" + destination + "/"])
        return {"case_id": case_id, "input_bytes": total}

    @server.tool()
    def download_simulation_result(job_id: str, archive_sha256: str, destination: str) -> dict:
        """Download a finished result archive and verify SHA256; remote cleanup remains explicit."""
        identifier(job_id)
        target = local_path(destination)
        target.mkdir(parents=True, exist_ok=True)
        archive = target / (job_id + ".tar.gz")
        if archive.exists():
            raise ValueError("Destination archive already exists; choose a new directory")
        partial = archive.with_suffix(".partial")
        call(["scp", "-o", "BatchMode=yes", "-o", "ClearAllForwardings=yes",
              host + ":" + str(remote / "jobs" / job_id / "result.tar.gz"), str(partial)])
        h = hashlib.sha256()
        with partial.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                h.update(chunk)
        actual = h.hexdigest()
        if actual != archive_sha256:
            raise ValueError("Downloaded archive SHA256 mismatch; remote data must be preserved")
        partial.replace(archive)
        return {"job_id": job_id, "archive": str(archive), "sha256": actual,
                "verified": True, "next_step": "Extract locally and validate the task outputs before cleanup."}

    return server


def main() -> None:
    create_server(Path(os.environ["PRINCIPIA_CASE_ROOT"]), os.environ["PRINCIPIA_REMOTE_SIMULATION_ROOT"],
                  os.getenv("PRINCIPIA_SSH_HOST", "yan_yun")).run(transport="stdio")


if __name__ == "__main__":
    main()
