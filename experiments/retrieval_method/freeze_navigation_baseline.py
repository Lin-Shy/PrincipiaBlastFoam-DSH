"""冻结当前检索实现和原始语料；只复制白名单，不运行求解器或模型。"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def freeze(project, output):
    project, output = project.resolve(), output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    skill = project / ".dsh/skills/blastfoam-knowledge"
    current = json.loads((skill / "index/current.json").read_text())
    release = skill / "index/releases" / current["snapshot"]
    paths = []
    for name in ("src", "mcp_servers", "experiments/retrieval_method", "tests", "packages/principia-dsh-bundle"):
        paths.extend(p for p in (project / name).rglob("*")
                     if p.is_file() and p.suffix in (".py", ".mjs", ".json", ".md", ".yml", ".ts")
                     and not any(x in p.parts for x in ("__pycache__", "node_modules", "dist")))
    for name in ("scripts", "references", "corpus"):
        paths.extend(p for p in (skill / name).rglob("*") if p.is_file() and "__pycache__" not in p.parts)
    paths.extend(p for p in release.rglob("*") if p.is_file())
    paths.extend([skill / "index/current.json", skill / "SKILL.md", project / "pyproject.toml", project / "AGENTS.md"])
    hashes = {}
    for path in sorted(set(paths)):
        relative = path.relative_to(project).as_posix()
        before = digest(path)
        target = output / "project" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        if before != digest(target) or before != digest(path):
            raise ValueError("source changed during freeze: " + relative)
        hashes[relative] = before
    sys.path.insert(0, str(project))
    sys.path.insert(0, str(project / "src"))
    from mcp_servers.principia_retrieval.retrieval_service import PrincipiaRetrievalService
    from mcp_servers.principia_retrieval.knowledge_navigation import navigator
    service = PrincipiaRetrievalService()
    state = service.get_status()
    engine = navigator().engine
    # get_status carries LLM configuration metadata; keep only explicit safe fields.
    status = {k: v for k, v in state.items()
              if k in ("status", "knowledge_index", "case_nodes", "case_relationships", "known_cases", "project_root")}
    status["navigation_base_snapshot"] = engine.graph["base_snapshot"]
    status["navigation_snapshot"] = engine.graph["snapshot"]
    status["navigation_units"] = len(engine.units)
    status["navigation_edges"] = len(engine.graph["edges"])
    graph = json.loads((release / "graph.json").read_text())
    manifest = json.loads((release / "manifest.json").read_text())
    save(output / "runtime-status.json", status)
    save(output / "baseline-identity.json", {
        "schema": "navigation-baseline-v1", "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=project, text=True).strip(),
        "git_status": subprocess.check_output(["git", "status", "--porcelain=v1"], cwd=project, text=True).splitlines(),
        "release_snapshot": graph["snapshot"], "files": hashes,
        "node_kinds": dict(Counter(n["kind"] for n in graph["nodes"])),
        "edge_relations": dict(Counter(e["relation"] for e in graph["edges"])),
        "source_inventory": manifest["inventory"],
        "copy_and_runtime_check_seconds": time.monotonic() - started,
        "notes": ["Snapshot preserves the pre-existing dirty worktree; no git reset or source deletion.",
                  "Original runtime includes author notes and solver source under manual/. These are not user-guide evidence.",
                  "No question, answer or scoring input is part of the graph construction interface.",
                  "Snapshot duration includes copy and runtime loading; it is not graph construction cost."]})
    print(json.dumps({"snapshot": graph["snapshot"], "files": len(hashes), "status": status}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    freeze(args.project, args.output)
