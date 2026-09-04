from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from principia_core.utils.solver_logs import (
    resolve_solver_log_paths,
    solver_log_has_clean_end,
    solver_logs_missing_clean_end,
)


STATUS_FILENAME = "execution_status.json"


def execution_status_path(case_path: str | Path) -> Path:
    return Path(case_path) / STATUS_FILENAME


def build_execution_status(
    case_path: str | Path,
    report_text: str = "",
    parsed_report_status: Optional[str] = None,
) -> Dict[str, Any]:
    case_dir = Path(case_path)
    solver_logs = resolve_solver_log_paths(case_dir)
    missing_clean_end = solver_logs_missing_clean_end(case_dir)
    solver_log_has_end = solver_log_has_clean_end(case_dir)

    if solver_log_has_end:
        run_status = "completed"
        final_status = "success"
        status_reason = "All current solver logs contain clean End markers."
        status_source = "solver_log"
    elif parsed_report_status == "completed":
        run_status = "failed"
        final_status = "failed"
        if solver_logs:
            status_reason = (
                "Agent report claimed success, but these current solver logs have no clean End marker: "
                + ", ".join(str(path.relative_to(case_dir)) for path in missing_clean_end)
            )
        else:
            status_reason = "Agent report claimed success, but no current solver log was found."
        status_source = "solver_log_guard"
    else:
        run_status = "failed"
        final_status = "failed"
        if solver_logs:
            status_reason = (
                "Execution did not produce clean End markers for these current solver logs: "
                + ", ".join(str(path.relative_to(case_dir)) for path in missing_clean_end)
            )
        else:
            status_reason = "Execution did not produce a current solver log."
        status_source = "solver_log_guard"

    return {
        "schema_version": 1,
        "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "final_status": final_status,
        "run_status": run_status,
        "status_source": status_source,
        "status_reason": status_reason,
        "agent_report_status": parsed_report_status,
        "solver_log_has_clean_end": solver_log_has_end,
        "solver_logs": [str(path.relative_to(case_dir)) for path in solver_logs],
        "solver_logs_missing_clean_end": [str(path.relative_to(case_dir)) for path in missing_clean_end],
        "report_path": "execution_report.md",
        "report_excerpt": (report_text or "")[:2000],
    }


def write_execution_status(case_path: str | Path, status: Dict[str, Any]) -> Path:
    path = execution_status_path(case_path)
    path.write_text(json.dumps(status, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def read_execution_status(case_path: str | Path) -> Optional[Dict[str, Any]]:
    path = execution_status_path(case_path)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def status_run_completed(status: Optional[Dict[str, Any]]) -> bool:
    return bool(status and status.get("run_status") == "completed" and status.get("final_status") == "success")
