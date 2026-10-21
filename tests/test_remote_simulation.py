from __future__ import annotations
import json
import sys
import time
from pathlib import Path
import pytest
from principia_core.remote_simulation import SimulationRunner, TERMINAL
from mcp_servers.simulation.server import create_server
from mcp_servers.simulation.files import create_server as create_files_server


def stage(root: Path, case_id: str = "case1") -> Path:
    case = root / "incoming" / case_id
    (case / "system").mkdir(parents=True)
    (case / "system/controlDict").write_text("application blastFoam;", encoding="utf-8")
    (case / "Allrun").write_text("placeholder", encoding="utf-8")
    return case


def runner(tmp_path: Path, code: str) -> SimulationRunner:
    script = tmp_path / "fake_solver.py"
    script.write_text(code, encoding="utf-8")
    return SimulationRunner(tmp_path / "remote", [sys.executable, str(script)], min_free_bytes=0)


def finish(service: SimulationRunner, job_id: str) -> dict:
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        result = service.result(job_id)
        if result["state"] in TERMINAL:
            return result
        time.sleep(0.1)
    service.cancel(job_id)
    raise AssertionError("worker did not finish")


def test_job_survives_server_object_restart_and_requires_download_hash(tmp_path):
    service = runner(tmp_path, "from pathlib import Path\nPath('log.blastFoam').write_text('Time = 1\\nEnd\\n')\nprint('done')")
    stage(service.root)
    job = service.submit("case1")
    restarted = SimulationRunner(service.root, service.command, min_free_bytes=0)
    result = finish(restarted, job["job_id"])
    assert result["state"] == "completed"
    assert result["exit_code"] == 0
    assert result["ready"]
    assert result["solver_logs"][0]["clean_end_in_tail"]
    assert "done" in restarted.logs(job["job_id"])["stdout"]
    with pytest.raises(ValueError, match="matching"):
        restarted.cleanup(job["job_id"], "wrong")
    restarted.cleanup(job["job_id"], result["archive_sha256"])
    assert not (service.root / "jobs" / job["job_id"]).exists()
    assert not (service.root / "incoming/case1").exists()


@pytest.mark.parametrize("code,expected", [("raise SystemExit(7)", "failed"),
                                           ("import time; time.sleep(60)", "timed_out")])
def test_nonzero_and_timeout_are_not_success(tmp_path, code, expected):
    service = runner(tmp_path, code)
    stage(service.root)
    job = service.submit("case1", timeout_seconds=1)
    assert finish(service, job["job_id"])["state"] == expected


def test_capacity_and_cancel(tmp_path):
    service = runner(tmp_path, "import time; time.sleep(60)")
    stage(service.root)
    stage(service.root, "case2")
    job = service.submit("case1")
    try:
        with pytest.raises(RuntimeError, match="capacity"):
            service.submit("case2")
        service.cancel(job["job_id"])
        assert finish(service, job["job_id"])["state"] == "cancelled"
    finally:
        service.cancel(job["job_id"])


@pytest.mark.parametrize("case_id", ["../outside", "/absolute", "x; touch hacked"])
def test_reject_path_and_shell_injection(tmp_path, case_id):
    service = runner(tmp_path, "pass")
    with pytest.raises(ValueError):
        service.submit(case_id)


def test_space_limit_blocks_without_launch(tmp_path):
    service = runner(tmp_path, "pass")
    stage(service.root)
    service.min_free_bytes = 10**30
    with pytest.raises(RuntimeError, match="free space"):
        service.submit("case1")
    assert list((service.root / "jobs").iterdir()) == []


def test_mcp_tool_schemas_have_no_chapter3_contract(tmp_path):
    import asyncio
    server = create_server(tmp_path / "remote", [sys.executable, "fake.py"], min_free_bytes=0)
    names = {tool.name for tool in asyncio.run(server.list_tools())}
    assert names == {"get_simulation_service_status", "run_simulation", "get_simulation_status",
                     "get_simulation_log", "get_simulation_result", "cancel_simulation", "cleanup_simulation"}
    assert "complete_workflow" not in names
    files = create_files_server(tmp_path / "local", "/srv/simulation/runtime")
    assert {t.name for t in asyncio.run(files.list_tools())} == {
        "upload_simulation_case", "download_simulation_result"}
