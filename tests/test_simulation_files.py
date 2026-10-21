import asyncio
import json
from pathlib import Path
import pytest
from mcp.server.fastmcp.exceptions import ToolError
import mcp_servers.simulation.files as bridge


def invoke(server, name, arguments):
    result = asyncio.run(server.call_tool(name, arguments))
    return result


def test_upload_is_scoped_and_uses_sftp_without_inheriting_forwards(tmp_path, monkeypatch):
    local = tmp_path / "local"
    case = local / "case"
    (case / "system").mkdir(parents=True)
    (case / "Allrun").write_text("placeholder")
    (case / "system/controlDict").write_text("application blastFoam;")
    commands = []
    monkeypatch.setattr(bridge, "call", commands.append)
    server = bridge.create_server(local, "/srv/simulation/runtime")
    invoke(server, "upload_simulation_case", {"case_path": str(case)})
    assert len(commands) == 2
    assert commands[0][0] == "ssh"
    assert commands[1][0] == "scp"
    assert "ClearAllForwardings=yes" in commands[0]
    assert commands[1][-2] == case.as_posix() + "/."
    assert commands[1][-1].startswith("yan_yun:/srv/simulation/runtime/incoming/")
    with pytest.raises(ToolError, match="inside"):
        invoke(server, "upload_simulation_case", {"case_path": str(tmp_path)})
    assert len(commands) == 2


def test_download_verifies_hash_before_accepting_archive(tmp_path, monkeypatch):
    import hashlib
    local = tmp_path / "local"
    local.mkdir()
    def fake_copy(command):
        Path(command[-1]).write_bytes(b"archive")
    monkeypatch.setattr(bridge, "call", fake_copy)
    server = bridge.create_server(local, "/srv/simulation/runtime")
    with pytest.raises(ToolError, match="mismatch"):
        invoke(server, "download_simulation_result", {
            "job_id": "job1", "archive_sha256": "incorrect", "destination": str(local / "bad")})
    assert not (local / "bad/job1.tar.gz").exists()
    invoke(server, "download_simulation_result", {
        "job_id": "job1", "archive_sha256": hashlib.sha256(b"archive").hexdigest(),
        "destination": str(local / "good")})
    assert (local / "good/job1.tar.gz").read_bytes() == b"archive"
