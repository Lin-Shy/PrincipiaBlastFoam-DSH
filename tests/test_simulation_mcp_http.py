"""Exercise the real MCP HTTP protocol locally, without Linux solver/authentication."""
import asyncio
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


def test_remote_tools_over_real_http(tmp_path, monkeypatch):
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    root = tmp_path / "remote"
    case = root / "incoming/smoke"
    (case / "system").mkdir(parents=True)
    (case / "system/controlDict").write_text("application blastFoam;")
    (case / "Allrun").write_text("placeholder")
    fake = tmp_path / "fake.py"
    fake.write_text("from pathlib import Path\nPath('log.blastFoam').write_text('Time = 1\\nEnd\\n')\n")
    source = ("from pathlib import Path; from mcp_servers.simulation.server import create_server; "
              f"create_server(Path({str(root)!r}), [{sys.executable!r}, {str(fake)!r}], "
              f"port={port}, min_free_bytes=0).run(transport='streamable-http')")
    with (tmp_path / "server.log").open("w") as log:
        process = subprocess.Popen([sys.executable, "-c", source], stdout=log, stderr=log)
        try:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                try:
                    with socket.create_connection(("127.0.0.1", port), timeout=.2):
                        break
                except OSError:
                    if process.poll() is not None:
                        raise AssertionError((tmp_path / "server.log").read_text())
                    time.sleep(.1)
            else:
                raise AssertionError("HTTP MCP did not start")

            async def exercise():
                async with streamablehttp_client(f"http://127.0.0.1:{port}/mcp") as (receive, send, _):
                    async with ClientSession(receive, send) as session:
                        await session.initialize()
                        assert len((await session.list_tools()).tools) == 7
                        status = await session.call_tool("get_simulation_service_status", {})
                        assert not status.isError
                        submitted = await session.call_tool("run_simulation", {"case_id": "smoke"})
                        job_id = json.loads(submitted.content[0].text)["job_id"]
                        for _ in range(100):
                            response = await session.call_tool("get_simulation_result", {"job_id": job_id})
                            result = json.loads(response.content[0].text)
                            if result.get("ready"):
                                break
                            await asyncio.sleep(.1)
                        assert result["state"] == "completed"
                        assert Path(result["archive_path"]).is_file()
                        logs = await session.call_tool("get_simulation_log", {"job_id": job_id})
                        assert "End" in logs.content[0].text
                        cleaned = await session.call_tool("cleanup_simulation", {
                            "job_id": job_id, "downloaded_sha256": result["archive_sha256"]})
                        assert not cleaned.isError
            asyncio.run(exercise())
        finally:
            process.terminate()
            process.wait(timeout=10)
