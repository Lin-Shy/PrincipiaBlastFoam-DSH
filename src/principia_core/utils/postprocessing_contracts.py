from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List

from principia_core.utils.report_contracts import report_error_reasons


CALCULATE_IMPULSE_ERROR_RE = re.compile(
    r"(could not dete?rmine a pressure field|valid probe fields are|was not found in .*postProcessing)",
    flags=re.IGNORECASE,
)


def discover_probe_fields(case_path: str | Path, probes_name: str = "pressureProbes") -> List[str]:
    probes_dir = Path(case_path) / "postProcessing" / probes_name
    if not probes_dir.exists():
        return []

    fields: set[str] = set()
    for time_dir in probes_dir.iterdir():
        if not time_dir.is_dir():
            continue
        for field_file in time_dir.iterdir():
            if field_file.is_file() and field_file.stat().st_size > 0:
                fields.add(field_file.name)
    return sorted(fields)


def validate_calculate_impulse_inputs(
    case_path: str | Path,
    probes_name: str = "pressureProbes",
    pressure_field: str = "p",
) -> Dict[str, object]:
    fields = discover_probe_fields(case_path, probes_name)
    if pressure_field not in fields:
        return {
            "ok": False,
            "issue": (
                f"calculateImpulse requires {probes_name}/{pressure_field}, "
                f"but available probe fields are: {', '.join(fields) if fields else 'none'}"
            ),
            "fields": fields,
        }
    return {"ok": True, "issue": "", "fields": fields}


def validate_post_processing_output(case_path: str | Path, output: str) -> Dict[str, object]:
    text = output or ""
    issues = report_error_reasons(text)

    mentions_calculate_impulse = "calculateImpulse" in text
    if mentions_calculate_impulse and CALCULATE_IMPULSE_ERROR_RE.search(text):
        issues.append("calculateImpulse reported an invalid or missing pressure field")

    if mentions_calculate_impulse:
        impulse_check = validate_calculate_impulse_inputs(case_path)
        if not impulse_check["ok"]:
            issues.append(str(impulse_check["issue"]))

    return {
        "ok": not issues,
        "issues": issues,
    }
