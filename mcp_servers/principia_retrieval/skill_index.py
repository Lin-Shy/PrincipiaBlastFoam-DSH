"""Adapters exposing the published blastfoam-knowledge index to MCP services."""
from __future__ import annotations

from collections import defaultdict
import importlib.util
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SKILL_ROOT = PROJECT_ROOT / ".dsh/skills/blastfoam-knowledge"


def _load_knowledge_module():
    path = SKILL_ROOT / "scripts/knowledge.py"
    spec = importlib.util.spec_from_file_location("principia_skill_knowledge", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load knowledge index reader: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SkillKnowledgeIndex:
    """Validated view of the single knowledge graph published by the skill."""

    def __init__(self) -> None:
        self.api = _load_knowledge_module()
        self.release = self.api.release_path(SKILL_ROOT / "index")
        self.api.check_release(self.release, SKILL_ROOT / "corpus")
        self.graph = self.api.read_json(self.release / "graph.json")
        self.documents = self.api.read_json(self.release / "documents.json")
        self.manifest = self.api.read_json(self.release / "manifest.json")
        self.nodes = self.graph["nodes"]
        self.relationships = self.graph["edges"]
        self.id_to_node = {node["id"]: node for node in self.nodes}
        self.known_cases = sorted(
            node["path"].removeprefix("tutorials/")
            for node in self.nodes
            if node["kind"] == "case"
        )
        self.aliases = {
            source.removeprefix("tutorials/"): target.removeprefix("tutorials/")
            for source, target in self.graph.get("aliases", {}).items()
        }
        self.case_path_to_node_id = {
            case: f"case:tutorials/{case}" for case in self.known_cases
        }
        self.case_to_file_ids: dict[str, list[str]] = defaultdict(list)
        self.file_to_variable_ids: dict[str, list[str]] = defaultdict(list)
        for node in self.nodes:
            if node["kind"] == "file" and node["path"].startswith("tutorials/"):
                case = self._owner(node["path"])
                if case:
                    self.case_to_file_ids[case].append(node["id"])
            elif node["kind"] == "configuration" and node.get("case"):
                path = node["evidence"]["path"]
                self.file_to_variable_ids[f"file:{path}"].append(node["id"])

    def _owner(self, path: str) -> str | None:
        relative = path.removeprefix("tutorials/")
        return next(
            (case for case in sorted(self.known_cases, key=len, reverse=True)
             if relative == case or relative.startswith(case + "/")),
            None,
        )

    def normalize_file_reference(self, path: str, case: str) -> str:
        prefix = f"tutorials/{case}/"
        return path[len(prefix):] if path.startswith(prefix) else path

    def read_source(self, path: str, max_lines: int = 120) -> str:
        try:
            result = self.api.source(
                path, start=1, end=max_lines, skill=SKILL_ROOT,
                corpus=SKILL_ROOT / "corpus", index=SKILL_ROOT / "index",
            )
        except (OSError, ValueError) as error:
            return f"File access denied or unavailable in blastfoam-knowledge corpus: {error}"
        return "\n".join(line.split(": ", 1)[1] if ": " in line else line
                         for line in result["text"].splitlines())

    def read_evidence(self, evidence: dict[str, Any]) -> str:
        path = evidence.get("path", "")
        if path not in self.manifest["inventory"]:
            return ""
        source = self.api.confined(SKILL_ROOT / "corpus", path)
        if self.api.digest(source.read_bytes()) != self.manifest["inventory"][path]:
            raise ValueError("knowledge source changed since index publication")
        lines = source.read_text(encoding="utf-8").splitlines()
        start = max(1, int(evidence.get("line_start", 1)))
        end = min(len(lines), int(evidence.get("line_end", start + 119)))
        return "\n".join(lines[start - 1:end])

    def query(self, text: str, *, mode: str = "search", case: str | None = None,
              limit: int = 5) -> dict[str, Any]:
        return self.api.query(
            text, mode=mode, case=case, limit=limit, skill=SKILL_ROOT,
            corpus=SKILL_ROOT / "corpus", index=SKILL_ROOT / "index",
        )


class SkillCaseRetriever:
    def __init__(self, index: SkillKnowledgeIndex) -> None:
        self.index = index
        self.nodes = index.nodes
        self.relationships = index.relationships
        self.id_to_node = index.id_to_node
        self.case_path_to_node_id = index.case_path_to_node_id
        self.case_to_file_ids = index.case_to_file_ids
        self.file_to_variable_ids = index.file_to_variable_ids

    def _normalize_file_reference(self, path: str, case: str) -> str:
        return self.index.normalize_file_reference(path, case)

    def _get_file_content(self, path: str, max_lines: int = 120) -> str:
        return self.index.read_source("tutorials/" + path.removeprefix("tutorials/"), max_lines)

    def search_detailed(self, query: str, top_k: int = 5,
                        include_file_content: bool = False, **_: Any) -> dict[str, Any]:
        result = self.index.query(query, limit=top_k)
        structured = []
        for hit in result.get("results", []):
            evidence = hit["evidence"]
            case = (hit.get("case") or "").removeprefix("tutorials/")
            item = {
                "case_path": case,
                "file_path": self.index.normalize_file_reference(evidence["path"], case),
                "node_id": hit["id"],
                "score": hit["score"],
                "evidence": evidence,
            }
            if include_file_content:
                item["file_content"] = self.index.read_source(evidence["path"])
            structured.append(item)
        return {"found": bool(structured), "structured_results": structured,
                "node_ids": [item["node_id"] for item in structured]}


class SkillUserGuideRetriever:
    def __init__(self, index: SkillKnowledgeIndex) -> None:
        self.index = index
        self.id_to_node = index.id_to_node

    def candidates(self, query: str, top_k: int) -> list[dict[str, Any]]:
        result = self.index.query(query, mode="manual", limit=top_k)
        return result.get("results", [])

    def _retrieve_full_content(self, node_ids: list[str]) -> str:
        chunks = []
        for node_id in node_ids:
            node = self.id_to_node.get(node_id, {})
            evidence = node.get("evidence", {})
            if evidence.get("path"):
                chunks.append(self.index.read_evidence(evidence))
        return "\n\n".join(chunks)
