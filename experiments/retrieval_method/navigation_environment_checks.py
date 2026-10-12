"""归档项目要求的只读/单元验证；profile原始输出不写盘，避免凭据泄露。"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def save(path, result):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")


async def mcp_check(project):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    environment = {**os.environ, "PYTHONPATH": str(project) + os.pathsep + str(project / "src"),
                   "ENABLE_EXECUTION": "false", "REQUIRE_EXECUTION": "false"}
    server = StdioServerParameters(command=sys.executable, args=["-m", "mcp_servers.principia_retrieval.server"],
                                  cwd=str(project), env=environment)
    async with stdio_client(server) as (reader, writer):
        async with ClientSession(reader, writer) as session:
            await session.initialize()
            tools = await session.list_tools()
            result = await session.call_tool("get_status", {})
            if result.isError:
                text = "\n".join(x.text for x in result.content if x.type == "text")
                return {"status": "FAIL", "tools": [x.name for x in tools.tools],
                        "called_tools": ["get_status"], "execution_enabled": False,
                        "error_text_sha256": hashlib.sha256(text.encode()).hexdigest(),
                        "missing_reviewed_defaults": "98_reviewed_defaults.md" in text,
                        "note": "MCP returned a tool error. Raw error not persisted; do not parse it as a successful JSON response."}
            data = json.loads(next(x.text for x in result.content if x.type == "text"))
            return {"status": "PASS" if not result.isError else "FAIL", "tools": [x.name for x in tools.tools],
                    "called_tools": ["get_status"], "case_nodes": data.get("case_nodes"),
                    "case_relationships": data.get("case_relationships"), "knowledge_index": data.get("knowledge_index"),
                    "execution_enabled": False}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("check", choices=("python", "bundle", "profile", "mcp"))
    p.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[2])
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--dsh", default="principia-dsh")
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    begin = time.monotonic()
    if args.check == "mcp":
        result = asyncio.run(mcp_check(args.project.resolve()))
    else:
        commands = {"python": [sys.executable, "-m", "pytest"], "bundle": ["npm", "run", "check"],
                    "profile": [args.dsh, "--profile", "web", "--dump-config"]}
        directory = args.project / "packages/principia-dsh-bundle" if args.check == "bundle" else args.project
        proc = subprocess.run(commands[args.check], cwd=directory, text=True, capture_output=True, timeout=300,
                              env={**os.environ, "ENABLE_EXECUTION": "false"})
        result = {"status": "PASS" if proc.returncode == 0 else "FAIL", "exit_code": proc.returncode}
        if args.check == "profile":
            result.update(stdout_sha256=hashlib.sha256(proc.stdout.encode()).hexdigest(),
                          stdout_characters=len(proc.stdout), stderr_characters=len(proc.stderr),
                          principia_mcp_configured="principia_retrieval" in proc.stdout or "principia-retrieval-mcp" in proc.stdout,
                          note="Raw config deliberately not persisted or printed; dump success is distinct from MCP connectivity.")
        else:
            (args.output / (args.check + ".log")).write_text(proc.stdout + proc.stderr)
            result["output_tail"] = (proc.stdout + proc.stderr)[-1400:]
    result["elapsed_seconds"] = time.monotonic() - begin
    save(args.output / (args.check + ".json"), result)
    print(json.dumps(result, ensure_ascii=False))
    if result["status"] != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
