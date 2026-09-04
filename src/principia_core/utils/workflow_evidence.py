from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from principia_core.utils.execution_status import read_execution_status
from principia_core.utils.openfoam_diagnostics import classify_case_openfoam_logs, summarize_diagnostics
from principia_core.utils.solver_logs import resolve_solver_log_paths, solver_log_has_clean_end
from principia_core.utils.time_dirs import (
    NUMERIC_TIME_DIR_RE,
    discover_numeric_time_dirs,
    unique_numeric_time_values,
)


EVIDENCE_JSON_FILENAME = "workflow_evidence.json"
EVIDENCE_MD_FILENAME = "workflow_evidence.md"
def _utc_iso_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_text(path: Path, max_chars: int = 20000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")[:max_chars]
    except OSError:
        return ""


def _tail_text(path: Path, max_chars: int = 2500) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
    return text[-max_chars:]


def _parse_dict_scalar(text: str, keyword: str) -> Optional[str]:
    match = re.search(rf"^\s*{re.escape(keyword)}\s+([^;]+);", text, flags=re.MULTILINE)
    return match.group(1).strip() if match else None


def _numeric_time_dirs(case_dir: Path) -> list[str]:
    return unique_numeric_time_values(discover_numeric_time_dirs(case_dir))


def _sample_items(items: list[str], edge_count: int = 8) -> list[str]:
    if len(items) <= edge_count * 2 + 1:
        return items
    return items[:edge_count] + ["..."] + items[-edge_count:]


def _reports_summary(case_dir: Path, names: Iterable[str]) -> Dict[str, Dict[str, Any]]:
    reports: Dict[str, Dict[str, Any]] = {}
    for name in names:
        path = case_dir / name
        reports[name] = {
            "exists": path.exists(),
            "bytes": path.stat().st_size if path.exists() else 0,
        }
    return reports


def _post_processing_summary(case_dir: Path, max_files: int = 80) -> Dict[str, Any]:
    root = case_dir / "postProcessing"
    if not root.exists():
        return {"exists": False, "files": []}

    files = []
    for path in sorted(root.rglob("*")):
        if path.is_file():
            files.append(
                {
                    "path": str(path.relative_to(case_dir)),
                    "bytes": path.stat().st_size,
                }
            )
        if len(files) >= max_files:
            break
    return {"exists": True, "files": files, "truncated": len(files) >= max_files}


def build_workflow_evidence(case_path: str | Path) -> Dict[str, Any]:
    case_dir = Path(case_path)
    control_dict = _read_text(case_dir / "system" / "controlDict")
    solver_logs = resolve_solver_log_paths(case_dir)
    diagnostics = classify_case_openfoam_logs(case_dir)

    time_dir_locations = discover_numeric_time_dirs(case_dir)
    time_dirs = unique_numeric_time_values(time_dir_locations)

    return {
        "schema_version": 1,
        "created_at": _utc_iso_timestamp(),
        "case_path": str(case_dir),
        "control": {
            "application": _parse_dict_scalar(control_dict, "application"),
            "endTime": _parse_dict_scalar(control_dict, "endTime"),
            "writeInterval": _parse_dict_scalar(control_dict, "writeInterval"),
        },
        "time_dir_count": len(time_dirs),
        "time_dirs": _sample_items(time_dirs),
        "first_time_dirs": time_dirs[:5],
        "last_time_dirs": time_dirs[-5:],
        "time_dir_locations": time_dir_locations[:80],
        "reports": _reports_summary(
            case_dir,
            [
                "physics_report.md",
                "execution_report.md",
                "execution_status.json",
                "review_report.md",
                "artifact_contract.json",
            ],
        ),
        "execution_status": read_execution_status(case_dir),
        "solver": {
            "clean_end": solver_log_has_clean_end(case_dir),
            "logs": [str(path.relative_to(case_dir)) for path in solver_logs],
            "tails": {str(path.relative_to(case_dir)): _tail_text(path) for path in solver_logs[:3]},
        },
        "openfoam_diagnostic_summary": summarize_diagnostics(diagnostics),
        "openfoam_diagnostics": diagnostics[:25],
        "post_processing": _post_processing_summary(case_dir),
    }


def format_workflow_evidence_markdown(evidence: Dict[str, Any]) -> str:
    control = evidence.get("control") or {}
    execution_status = evidence.get("execution_status") or {}
    diagnostics_summary = evidence.get("openfoam_diagnostic_summary") or {}
    reports = evidence.get("reports") or {}
    post_processing = evidence.get("post_processing") or {}

    lines = [
        "# Workflow Evidence",
        "",
        f"- Case path: `{evidence.get('case_path')}`",
        f"- Created at: `{evidence.get('created_at')}`",
        f"- Application: `{control.get('application')}`",
        f"- endTime: `{control.get('endTime')}`",
        f"- writeInterval: `{control.get('writeInterval')}`",
        f"- Time directory count: `{evidence.get('time_dir_count')}`",
        f"- Time directory sample: `{', '.join(evidence.get('time_dirs') or [])}`",
        f"- Solver clean End: `{(evidence.get('solver') or {}).get('clean_end')}`",
        f"- Execution status: `{execution_status.get('run_status')}` / `{execution_status.get('final_status')}`",
        f"- Execution status source: `{execution_status.get('status_source')}`",
        f"- OpenFOAM blocking diagnostics: `{diagnostics_summary.get('blocking', 0)}`",
        "",
        "## Reports",
    ]
    for name, summary in reports.items():
        lines.append(f"- `{name}`: exists={summary.get('exists')}, bytes={summary.get('bytes')}")

    lines.extend(["", "## OpenFOAM Diagnostics"])
    categories = diagnostics_summary.get("categories") or {}
    if categories:
        for category, count in sorted(categories.items()):
            lines.append(f"- `{category}`: {count}")
    else:
        lines.append("- None detected.")

    lines.extend(["", "## Post Processing"])
    lines.append(f"- postProcessing exists: `{post_processing.get('exists')}`")
    for item in (post_processing.get("files") or [])[:30]:
        lines.append(f"- `{item.get('path')}` ({item.get('bytes')} bytes)")

    solver = evidence.get("solver") or {}
    tails = solver.get("tails") or {}
    if tails:
        lines.extend(["", "## Solver Log Tails"])
        for name, tail in tails.items():
            compact_tail = "\n".join(tail.splitlines()[-40:])
            lines.extend([f"### `{name}`", "```text", compact_tail, "```"])

    return "\n".join(lines).rstrip() + "\n"


def write_workflow_evidence(case_path: str | Path) -> Dict[str, Any]:
    evidence = build_workflow_evidence(case_path)
    case_dir = Path(case_path)
    (case_dir / EVIDENCE_JSON_FILENAME).write_text(
        json.dumps(evidence, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    (case_dir / EVIDENCE_MD_FILENAME).write_text(
        format_workflow_evidence_markdown(evidence),
        encoding="utf-8",
    )
    return evidence
