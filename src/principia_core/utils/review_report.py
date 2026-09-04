from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Optional

from principia_core.utils.execution_status import read_execution_status, status_run_completed
from principia_core.utils.openfoam_diagnostics import classify_case_openfoam_logs, summarize_diagnostics


VALIDATION_STATUS_RE = re.compile(r"^\s*Validation Status:\s*(Passed|Failed)\s*$", re.IGNORECASE | re.MULTILINE)


def read_review_validation_status(case_path: str | Path) -> Optional[str]:
    path = Path(case_path) / "review_report.md"
    if not path.exists():
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None
    match = VALIDATION_STATUS_RE.search(text)
    if not match:
        return None
    return match.group(1).lower()


def write_deterministic_review_report(
    case_path: str | Path,
    *,
    require_execution: bool,
    reason: str = "",
) -> dict[str, Any]:
    case_dir = Path(case_path)
    status = read_execution_status(case_dir)
    diagnostics = classify_case_openfoam_logs(case_dir)
    diagnostics_summary = summarize_diagnostics(diagnostics)
    blocking_count = int(diagnostics_summary.get("blocking", 0) or 0)

    reports = {
        "physics_report.md": (case_dir / "physics_report.md").exists(),
        "execution_report.md": (case_dir / "execution_report.md").exists(),
        "execution_status.json": (case_dir / "execution_status.json").exists(),
        "workflow_evidence.md": (case_dir / "workflow_evidence.md").exists(),
    }

    execution_ok = status_run_completed(status) if require_execution else True
    reports_ok = reports["physics_report.md"] and (reports["execution_report.md"] or not require_execution)
    passed = reports_ok and execution_ok and blocking_count == 0
    validation_status = "Passed" if passed else "Failed"

    status_text = (
        f"{status.get('run_status')} / {status.get('final_status')}"
        if isinstance(status, dict)
        else "unavailable"
    )
    solver_logs = ", ".join(status.get("solver_logs") or []) if isinstance(status, dict) else ""
    missing_end = ", ".join(status.get("solver_logs_missing_clean_end") or []) if isinstance(status, dict) else ""

    lines = [
        "# Review Report",
        "",
        f"Validation Status: {validation_status}",
        "",
        "## Checklist",
        f"- `physics_report.md`: {'present' if reports['physics_report.md'] else 'missing'}",
        f"- `execution_report.md`: {'present' if reports['execution_report.md'] else 'missing'}",
        f"- `execution_status.json`: {'present' if reports['execution_status.json'] else 'missing'}",
        f"- `workflow_evidence.md`: {'present' if reports['workflow_evidence.md'] else 'missing'}",
        f"- OpenFOAM blocking diagnostics: `{blocking_count}`",
        "",
        "## Execution",
        f"- Execution required: `{require_execution}`",
        f"- Execution status: `{status_text}`",
        f"- Status source: `{status.get('status_source') if isinstance(status, dict) else 'unavailable'}`",
        f"- Status reason: {status.get('status_reason') if isinstance(status, dict) else 'unavailable'}",
        f"- Solver logs: `{solver_logs or 'none'}`",
    ]
    if missing_end:
        lines.append(f"- Solver logs missing clean End: `{missing_end}`")
    if reason:
        lines.extend(["", "## Review Note", reason])
    if not passed:
        lines.extend(
            [
                "",
                "## Next Actions",
                "- Regenerate missing reports or rerun controlled execution.",
                "- Inspect `workflow_evidence.md`, `execution_status.json`, and `artifact_contract.json`.",
            ]
        )
    else:
        lines.extend(
            [
                "",
                "## Conclusion",
                "The required workflow artifacts and deterministic execution evidence satisfy the validation contract.",
            ]
        )

    path = case_dir / "review_report.md"
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return {
        "path": str(path),
        "validation_status": validation_status.lower(),
        "passed": passed,
        "blocking_diagnostics": blocking_count,
        "execution_status": status_text,
    }
