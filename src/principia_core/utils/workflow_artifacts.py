from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from principia_core.utils.execution_status import read_execution_status, status_run_completed
from principia_core.utils.openfoam_diagnostics import classify_case_openfoam_logs, summarize_diagnostics
from principia_core.utils.report_contracts import validate_agent_report
from principia_core.utils.review_report import read_review_validation_status


ARTIFACT_CONTRACT_FILENAME = "artifact_contract.json"


REPORT_CONTRACTS = {
    "physics_report.md": 120,
    "execution_report.md": 120,
    "post_processing_report.md": 120,
    "review_report.md": 120,
}


def artifact_contract_path(case_path: str | Path) -> Path:
    return Path(case_path) / ARTIFACT_CONTRACT_FILENAME


def _utc_iso_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_report(case_dir: Path, name: str) -> tuple[bool, str]:
    path = case_dir / name
    if not path.exists():
        return False, ""
    try:
        return True, path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return True, ""


def _report_check(case_dir: Path, name: str) -> Dict[str, Any]:
    exists, text = _read_report(case_dir, name)
    validation = validate_agent_report(
        text,
        name.replace(".md", ""),
        min_chars=REPORT_CONTRACTS.get(name, 80),
    )
    return {
        "exists": exists,
        "valid": bool(exists and validation["valid"]),
        "reason": "" if exists and validation["valid"] else validation["reason"] or f"{name} is missing",
        "reasons": [] if exists and validation["valid"] else validation["reasons"] or [f"{name} is missing"],
        "excerpt": validation.get("excerpt", ""),
    }


def validate_workflow_artifacts(
    case_path: str | Path,
    state: Optional[Dict[str, Any]] = None,
    *,
    require_execution: bool = False,
    require_review: bool = False,
) -> Dict[str, Any]:
    """Validate terminal workflow artifacts with deterministic checks.

    The verifier is intentionally case-agnostic. It checks generic contracts:
    report existence/content, authoritative execution status, OpenFOAM blocking
    diagnostics, and final reviewer status when review is required.
    """
    case_dir = Path(case_path)
    state = state or {}
    issues: list[str] = []
    checks: Dict[str, bool] = {}
    reports: Dict[str, Dict[str, Any]] = {}

    physics = _report_check(case_dir, "physics_report.md")
    reports["physics_report.md"] = physics
    checks["physics_report_valid"] = physics["valid"]
    if not physics["valid"]:
        issues.append(f"physics_report.md invalid: {physics['reason']}")

    if require_execution:
        execution_report = _report_check(case_dir, "execution_report.md")
        reports["execution_report.md"] = execution_report
        checks["execution_report_valid"] = execution_report["valid"]
        if not execution_report["valid"]:
            issues.append(f"execution_report.md invalid: {execution_report['reason']}")

        post_processing_report = _report_check(case_dir, "post_processing_report.md")
        reports["post_processing_report.md"] = post_processing_report
        checks["post_processing_report_valid"] = post_processing_report["valid"]
        if not post_processing_report["valid"]:
            issues.append(f"post_processing_report.md invalid: {post_processing_report['reason']}")

        execution_status = state.get("execution_status")
        if not isinstance(execution_status, dict):
            execution_status = read_execution_status(case_dir)

        checks["execution_status_present"] = isinstance(execution_status, dict)
        checks["execution_status_success"] = status_run_completed(execution_status)
        if not execution_status:
            issues.append("execution_status.json is missing or unreadable")
        elif not status_run_completed(execution_status):
            issues.append("execution_status.json does not mark execution successful")

        diagnostics = classify_case_openfoam_logs(case_dir)
        diagnostics_summary = summarize_diagnostics(diagnostics)
        checks["openfoam_blocking_diagnostics_absent"] = diagnostics_summary.get("blocking", 0) == 0
        if diagnostics_summary.get("blocking", 0):
            categories = diagnostics_summary.get("categories", {})
            blocking_categories = sorted(
                {
                    item.get("category", "unknown")
                    for item in diagnostics
                    if item.get("blocking")
                }
            )
            issues.append(
                "OpenFOAM blocking diagnostics present: "
                + ", ".join(blocking_categories or sorted(categories))
            )
    else:
        diagnostics = []
        diagnostics_summary = summarize_diagnostics([])

    if require_review:
        review_report = _report_check(case_dir, "review_report.md")
        reports["review_report.md"] = review_report
        checks["review_report_valid"] = review_report["valid"]
        if not review_report["valid"]:
            issues.append(f"review_report.md invalid: {review_report['reason']}")

        validation_status = state.get("validation_status")
        if validation_status is None:
            validation_status = read_review_validation_status(case_dir)
        checks["validation_status_passed"] = validation_status == "passed"
        if validation_status != "passed":
            issues.append(f"validation_status is not passed: {validation_status}")

    return {
        "schema_version": 1,
        "created_at": _utc_iso_timestamp(),
        "case_path": str(case_dir),
        "ok": not issues,
        "issues": issues,
        "checks": checks,
        "reports": reports,
        "openfoam_diagnostics": diagnostics,
        "openfoam_diagnostics_summary": diagnostics_summary,
    }


def write_artifact_contract(case_path: str | Path, contract: Dict[str, Any]) -> Path:
    path = artifact_contract_path(case_path)
    path.write_text(json.dumps(contract, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path
