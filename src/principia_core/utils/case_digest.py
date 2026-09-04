from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


NUMERIC_TIME_RE = re.compile(r"^\d+(?:\.\d+)?(?:[eE][+-]?\d+)?$")

CORE_CASE_FILES = [
    "system/controlDict",
    "system/setFieldsDict",
    "system/blockMeshDict",
    "system/fvSolution",
    "system/fvSchemes",
    "constant/phaseProperties",
    "constant/dynamicMeshDict",
    "Allrun",
    "README.md",
]

FIELD_GLOBS = ["0/*", "0.orig/*"]

CONTROL_ASSIGNMENTS = [
    "application",
    "startFrom",
    "startTime",
    "stopAt",
    "endTime",
    "writeControl",
    "writeInterval",
    "deltaT",
    "adjustTimeStep",
    "maxCo",
    "maxDeltaT",
]

IMPORTANT_LINE_PATTERNS = [
    r"\bapplication\b",
    r"\bendTime\b",
    r"\bwriteInterval\b",
    r"\bdeltaT\b",
    r"\bmaxCo\b",
    r"\bfunctions\b",
    r"\bblastProbes\b",
    r"\bprobeLocations\b",
    r"\bfields\b",
    r"\bimpulse\b",
    r"\boverpressure\b",
    r"\bdynamicPressure\b",
    r"\bsphereToCell\b",
    r"\bboxToCell\b",
    r"\bcylinderToCell\b",
    r"\bcentre\b",
    r"\bradius\b",
    r"\bfieldValues\b",
    r"\binternalField\b",
    r"\bboundaryField\b",
    r"\btype\b",
    r"\bpatches\b",
    r"\bboundary\b",
    r"\bvertices\b",
    r"\bblocks\b",
]


def _env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return max(minimum, min(maximum, value))


def _read_text(path: Path, max_chars: int) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n... [truncated by case digest]\n"


def _line_count(text: str) -> int:
    return len(text.splitlines()) if text else 0


def _assignment_map(text: str, keys: Iterable[str]) -> Dict[str, str]:
    values: Dict[str, str] = {}
    for key in keys:
        match = re.search(rf"(?m)^\s*{re.escape(key)}\s+([^;]+);", text)
        if match:
            values[key] = " ".join(match.group(1).split())
    return values


def _extract_named_block(text: str, name: str, max_chars: int = 1800) -> str:
    match = re.search(rf"(?m)^\s*{re.escape(name)}\s*\{{", text)
    if not match:
        return ""
    open_brace = text.find("{", match.start())
    if open_brace < 0:
        return ""
    depth = 0
    end = open_brace
    for index in range(open_brace, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                end = index + 1
                break
    block = text[match.start():end]
    if len(block) > max_chars:
        return block[:max_chars] + "\n... [block truncated]\n"
    return block


def _important_excerpt(text: str, max_chars: int = 1600) -> str:
    if not text:
        return ""
    patterns = [re.compile(pattern) for pattern in IMPORTANT_LINE_PATTERNS]
    selected: List[str] = []
    for line in text.splitlines():
        if any(pattern.search(line) for pattern in patterns):
            compact = line.rstrip()
            if compact and compact not in selected:
                selected.append(compact)
        if len("\n".join(selected)) >= max_chars:
            break
    excerpt = "\n".join(selected).strip()
    if not excerpt:
        excerpt = text[:max_chars].strip()
    if len(excerpt) > max_chars:
        excerpt = excerpt[:max_chars].rstrip() + "\n... [excerpt truncated]"
    return excerpt


def _function_names(control_text: str) -> List[str]:
    block = _extract_named_block(control_text, "functions", max_chars=5000)
    if not block:
        return []
    names = re.findall(r"(?m)^\s{4,}([A-Za-z_][A-Za-z0-9_.-]*)\s*$\n\s{4,}\{", block)
    return list(dict.fromkeys(names))


def _probe_locations(text: str, max_locations: int = 8) -> List[str]:
    locations: List[str] = []
    for match in re.finditer(r"probeLocations\s*\((.*?)\)\s*;", text, flags=re.S):
        for coord in re.findall(r"\([^\(\)]*\)", match.group(1)):
            coord = " ".join(coord.split())
            if coord not in locations:
                locations.append(coord)
            if len(locations) >= max_locations:
                return locations
    return locations


def _boundary_types(text: str, max_items: int = 16) -> List[str]:
    boundary = _extract_named_block(text, "boundaryField", max_chars=6000)
    if not boundary:
        boundary = _extract_named_block(text, "boundary", max_chars=6000)
    items: List[str] = []
    for patch_match in re.finditer(r"(?m)^\s{4,}([A-Za-z_][A-Za-z0-9_.-]*)\s*\{", boundary):
        patch = patch_match.group(1)
        tail = boundary[patch_match.end(): patch_match.end() + 500]
        type_match = re.search(r"(?m)^\s*type\s+([^;]+);", tail)
        if type_match:
            items.append(f"{patch}: {type_match.group(1).strip()}")
        else:
            items.append(patch)
        if len(items) >= max_items:
            break
    return items


def _field_summary(path: Path, rel_path: str, max_chars: int) -> str:
    text = _read_text(path, max_chars=max_chars)
    if not text:
        return f"### {rel_path}\n- Present but unreadable or empty.\n"
    assignments = _assignment_map(text, ["dimensions", "internalField"])
    boundary = _boundary_types(text, max_items=10)
    lines = [f"### {rel_path}", f"- Lines: {_line_count(text)}"]
    if assignments:
        lines.append("- Key entries: " + ", ".join(f"{k}={v}" for k, v in assignments.items()))
    if boundary:
        lines.append("- Boundary types: " + "; ".join(boundary))
    excerpt = _important_excerpt(text, max_chars=600)
    if excerpt:
        lines.append("```text")
        lines.append(excerpt)
        lines.append("```")
    return "\n".join(lines).rstrip() + "\n"


def _file_summary(case_dir: Path, rel_path: str, max_chars: int) -> Optional[str]:
    path = case_dir / rel_path
    if not path.exists() or not path.is_file():
        return None

    text = _read_text(path, max_chars=max_chars)
    lines = [f"### {rel_path}", f"- Lines: {_line_count(text)}"]

    if rel_path == "system/controlDict":
        assignments = _assignment_map(text, CONTROL_ASSIGNMENTS)
        if assignments:
            lines.append("- Key entries: " + ", ".join(f"{k}={v}" for k, v in assignments.items()))
        functions = _function_names(text)
        if functions:
            lines.append("- Function objects: " + ", ".join(functions[:12]))
        probes = _probe_locations(text)
        if probes:
            suffix = " ..." if len(probes) >= 8 else ""
            lines.append("- Probe locations: " + ", ".join(probes) + suffix)
    elif rel_path == "system/setFieldsDict":
        regions = re.findall(r"(?m)^\s{4,}(sphereToCell|boxToCell|cylinderToCell|cellToCell)\b", text)
        if regions:
            lines.append("- Region selectors: " + ", ".join(list(dict.fromkeys(regions))))
    elif rel_path == "system/blockMeshDict":
        assignments = _assignment_map(text, ["convertToMeters"])
        if assignments:
            lines.append("- Key entries: " + ", ".join(f"{k}={v}" for k, v in assignments.items()))
        boundary = _boundary_types(text, max_items=12)
        if boundary:
            lines.append("- Boundary patches: " + "; ".join(boundary))
    elif rel_path in {"Allrun", "README.md"}:
        pass
    else:
        assignments = _assignment_map(text, ["solver", "type", "method", "transportModel", "equationOfState"])
        if assignments:
            lines.append("- Key entries: " + ", ".join(f"{k}={v}" for k, v in assignments.items()))

    excerpt = _important_excerpt(text, max_chars=900)
    if excerpt:
        lines.append("```text")
        lines.append(excerpt)
        lines.append("```")
    return "\n".join(lines).rstrip() + "\n"


def _top_level_summary(case_dir: Path) -> Dict[str, Any]:
    if not case_dir.exists():
        return {"exists": False}
    children = sorted(case_dir.iterdir(), key=lambda path: path.name)
    return {
        "exists": True,
        "top_level": [child.name + ("/" if child.is_dir() else "") for child in children[:80]],
        "time_dirs": [child.name for child in children if child.is_dir() and NUMERIC_TIME_RE.match(child.name)][:20],
        "log_files": [child.name for child in children if child.is_file() and child.name.startswith("log.")][:20],
    }


def _field_files(case_dir: Path, max_files: int) -> List[str]:
    files: List[str] = []
    for pattern in FIELD_GLOBS:
        for path in sorted(case_dir.glob(pattern), key=lambda item: str(item)):
            if path.is_file():
                files.append(str(path.relative_to(case_dir)))
            if len(files) >= max_files:
                return files
    return files


def _compact_digest(text: str, max_chars: int) -> str:
    content = text.strip()
    if len(content) <= max_chars:
        return content
    marker = "\n\n[Digest compacted: middle file excerpts omitted.]\n\n"
    tail_chars = min(1200, max_chars // 4)
    head_chars = max_chars - len(marker) - tail_chars
    if head_chars < 1000:
        return content[:max_chars]
    return content[:head_chars].rstrip() + marker + content[-tail_chars:].lstrip()


def build_physics_case_digest(
    case_path: str | os.PathLike[str],
    *,
    user_request: str = "",
    tutorial_case_path: str | None = None,
    tutorial_source_path: str | None = None,
) -> Dict[str, Any]:
    """Build a bounded, deterministic digest for the physics analysis prompt."""
    case_dir = Path(case_path)
    max_chars = _env_int("PHYSICS_DIGEST_MAX_CHARS", 12000, 4000, 30000)
    per_file_chars = _env_int("PHYSICS_DIGEST_FILE_MAX_CHARS", 3500, 800, 8000)
    max_field_files = _env_int("PHYSICS_DIGEST_FIELD_FILES", 6, 0, 20)

    top_level = _top_level_summary(case_dir)
    missing_core = [
        rel_path
        for rel_path in ("system/controlDict", "system/blockMeshDict")
        if not (case_dir / rel_path).exists()
    ]
    included: List[str] = []

    lines = [
        "# Programmatic Case Digest",
        f"- Case path: `{case_dir}`",
        f"- Case exists: {top_level.get('exists', False)}",
    ]
    if tutorial_case_path:
        lines.append(f"- Selected tutorial case: `{tutorial_case_path}`")
    if tutorial_source_path:
        lines.append(f"- Tutorial source path: `{tutorial_source_path}`")
    if user_request:
        lines.append(f"- User request excerpt: {user_request[:600]}")

    if top_level.get("exists"):
        lines.append("- Top-level entries: " + ", ".join(top_level.get("top_level", [])))
        if top_level.get("time_dirs"):
            lines.append("- Existing time directories: " + ", ".join(top_level["time_dirs"]))
        if top_level.get("log_files"):
            lines.append("- Existing log files: " + ", ".join(top_level["log_files"]))
    if missing_core:
        lines.append("- Missing core files: " + ", ".join(missing_core))
    else:
        lines.extend(
            [
                "",
                "## Recommended Next Action",
                "For tutorial-based smoke/benchmark requests with bounded `endTime` or `writeInterval` edits, call `complete_workflow` next. It applies the requested controls, writes reports/evidence, runs the solver when required, and validates artifacts. Do not read full OpenFOAM dictionaries unless `complete_workflow` reports failure or the user explicitly requires novel modeling beyond tutorial adaptation.",
            ]
        )

    lines.append("\n## Core Configuration Evidence")
    for rel_path in CORE_CASE_FILES:
        summary = _file_summary(case_dir, rel_path, max_chars=per_file_chars)
        if summary:
            included.append(rel_path)
            lines.append(summary)

    field_files = _field_files(case_dir, max_field_files)
    if field_files:
        lines.append("\n## Initial Field Evidence")
        for rel_path in field_files:
            included.append(rel_path)
            lines.append(_field_summary(case_dir / rel_path, rel_path, max_chars=per_file_chars))

    markdown = _compact_digest("\n".join(lines), max_chars=max_chars)
    return {
        "markdown": markdown,
        "case_path": str(case_dir),
        "files_included": included,
        "missing_core_files": missing_core,
        "requires_deep_analysis": bool(missing_core or not top_level.get("exists")),
        "max_chars": max_chars,
    }
