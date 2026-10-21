"""Loopback-only simulation MCP, shared by Chapter 3 and independent RSI."""
from __future__ import annotations
import os
import shutil
from pathlib import Path
from mcp.server.fastmcp import FastMCP
from principia_core.remote_simulation import SimulationRunner


def create_server(root: Path, command: list[str], *, port: int = 8000,
                  min_free_bytes: int = 2 * 1024**3) -> FastMCP:
    runner = SimulationRunner(root, command, min_free_bytes=min_free_bytes,
                              max_jobs=int(os.getenv("SIMULATION_MAX_JOBS", "1")))
    server = FastMCP("principia-simulation", host="127.0.0.1", port=port,
                     stateless_http=True, json_response=True)

    @server.tool()
    def get_simulation_service_status() -> dict:
        """Read capacity and free disk space without starting a solver."""
        return {"root": str(runner.root), "max_jobs": runner.max_jobs,
                "free_bytes": shutil.disk_usage(runner.root).free,
                "jobs": [runner.status(p.parent.name) for p in (runner.root / "jobs").glob("*/status.json")]}

    @server.tool()
    def run_simulation(case_id: str, timeout_seconds: int = 3600) -> dict:
        """Submit an SFTP-uploaded incoming/<case_id> case; return a job ID immediately."""
        return runner.submit(case_id, timeout_seconds)

    @server.tool()
    def get_simulation_status(job_id: str) -> dict:
        """Poll job status. completed means exit 0, not physical/task correctness."""
        return runner.status(job_id)

    @server.tool()
    def get_simulation_log(job_id: str, tail_lines: int = 100) -> dict:
        """Read bounded runner/solver log tails."""
        return runner.logs(job_id, tail_lines)

    @server.tool()
    def get_simulation_result(job_id: str) -> dict:
        """Return archive location and SHA256 for SFTP download, plus limited log evidence."""
        return runner.result(job_id)

    @server.tool()
    def cancel_simulation(job_id: str) -> dict:
        """Request termination of the solver process group."""
        return runner.cancel(job_id)

    @server.tool()
    def cleanup_simulation(job_id: str, downloaded_sha256: str) -> dict:
        """Remove finished remote data after the downloaded archive hash matches."""
        return runner.cleanup(job_id, downloaded_sha256)

    return server


def main() -> None:
    if os.name != "posix":
        raise SystemExit("Run the simulation service on Linux and forward it over SSH.")
    script = Path(os.environ["SIMULATION_RUN_SCRIPT"]).expanduser().resolve(strict=True)
    create_server(Path(os.environ["SIMULATION_ROOT"]), ["bash", str(script)],
                  port=int(os.getenv("SIMULATION_PORT", "8000")),
                  min_free_bytes=int(os.getenv("SIMULATION_MIN_FREE_BYTES", str(2 * 1024**3)))).run(transport="streamable-http")


if __name__ == "__main__":
    main()
