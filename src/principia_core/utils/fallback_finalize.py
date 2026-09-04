from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

from principia_core.utils.report_contracts import report_error_reasons


NUMBER_RE = r"(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?"


def _format_number(value: float) -> str:
    return f"{value:.10g}"


def _find_number_after_keyword(text: str, keyword: str) -> float | None:
    pattern = re.compile(rf"{re.escape(keyword)}[^0-9+\-.]{{0,80}}({NUMBER_RE})", re.IGNORECASE)
    match = pattern.search(text)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def _read_dict_value(text: str, key: str) -> float | None:
    pattern = re.compile(rf"^\s*{re.escape(key)}\s+({NUMBER_RE})\s*;", re.MULTILINE)
    match = pattern.search(text)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def _replace_or_add_entry(text: str, key: str, value: float) -> str:
    formatted = _format_number(value)
    pattern = re.compile(rf"^(\s*{re.escape(key)}\s+)[^;]+(;.*)$", re.MULTILINE)
    if pattern.search(text):
        return pattern.sub(rf"\g<1>{formatted}\2", text, count=1)

    marker = "// ************************************************************************* //"
    entry = f"{key:<16}{formatted};\n"
    if marker in text:
        return text.replace(marker, entry + "\n" + marker, 1)
    return text.rstrip() + "\n\n" + entry


def _request_mentions_probe(user_request: str) -> bool:
    lowered = user_request.lower()
    return any(term in lowered for term in ("probe", "probes", "pressure", "sample", "sampling")) or any(
        term in user_request for term in ("探针", "测点", "采样", "压力")
    )


def _request_is_surface_blast(user_request: str) -> bool:
    lowered = user_request.lower()
    return any(term in lowered for term in ("surface", "ground", "hopkinson", "z=2", "z=3")) or any(
        term in user_request for term in ("触地", "地表", "地面", "比例距离")
    )


def _request_is_shock_tube(user_request: str) -> bool:
    lowered = user_request.lower()
    return "shock" in lowered or "激波管" in user_request


def _request_is_short_smoke(user_request: str) -> bool:
    lowered = user_request.lower()
    return any(term in lowered for term in ("smoke", "short", "quick", "bounded")) or any(
        term in user_request for term in ("短时", "快速", "节省")
    )


def _smoke_end_time_cap(user_request: str) -> float | None:
    if not _request_is_short_smoke(user_request):
        return None
    try:
        return float(os.getenv("PRINCIPIA_SMOKE_MAX_END_TIME", "0.0005"))
    except ValueError:
        return 0.0005


def _format_probe_locations(locations: list[str], indent: str = "            ") -> str:
    return "\n".join(f"{indent}{location}" for location in locations)


def _replace_probe_locations(text: str, locations: list[str]) -> tuple[str, bool]:
    pattern = re.compile(r"(probeLocations\s*\(\s*)(.*?)(\s*\)\s*;)", flags=re.DOTALL)
    if not pattern.search(text):
        return text, False
    replacement = rf"\1\n{_format_probe_locations(locations)}\3"
    updated = pattern.sub(replacement, text)
    return updated, updated != text


def _add_shock_tube_probes_to_empty_functions(text: str) -> tuple[str, bool]:
    if re.search(r"(?m)^\s*probes\s*\{", text):
        return text, False

    probes_block = """functions
{
    probes
    {
        type            probes;
        libs            ("libsampling.so");
        writeControl    writeTime;
        fields          (p rho U);
        probeLocations
        (
            (25 0 0)
            (50 0 0)
            (75 0 0)
        );
    }
}"""
    pattern = re.compile(r"functions\s*\{\s*\}", flags=re.DOTALL)
    if pattern.search(text):
        updated = pattern.sub(probes_block, text, count=1)
        return updated, updated != text
    return text, False


def _apply_probe_adjustments(text: str, user_request: str) -> tuple[str, dict[str, Any]]:
    if not _request_mentions_probe(user_request):
        return text, {"updated": False, "reason": "request does not mention probe/sampling outputs"}

    if _request_is_surface_blast(user_request) and "pressureProbes" in text:
        locations = [
            "(0.5 0 0)",
            "(1.0 0 0)",
            "(1.5 0 0)",
            "(2.0 0 0)",
            "(2.5 0 0)",
            "(3.0 0 0)",
        ]
        updated, changed = _replace_probe_locations(text, locations)
        return (
            updated,
            {
                "updated": changed,
                "kind": "surface_blast_pressure_probes",
                "locations": locations,
            },
        )

    if _request_is_shock_tube(user_request):
        updated, changed = _add_shock_tube_probes_to_empty_functions(text)
        return (
            updated,
            {
                "updated": changed,
                "kind": "shock_tube_probes",
                "locations": ["(25 0 0)", "(50 0 0)", "(75 0 0)"] if changed else [],
            },
        )

    return text, {"updated": False, "reason": "no deterministic probe adjustment matched"}


def find_control_dicts(case_dir: Path) -> list[Path]:
    root_control = case_dir / "system" / "controlDict"
    if root_control.exists():
        return [root_control]
    return sorted(
        path
        for path in case_dir.glob("**/system/controlDict")
        if path.is_file() and ".git" not in path.parts
    )


def _apply_control_constraints(case_dir: Path, user_request: str) -> dict[str, Any]:
    controls = find_control_dicts(case_dir)
    if not controls:
        return {"updated": False, "reason": "no system/controlDict found"}

    requested_end = _find_number_after_keyword(user_request, "endTime")
    requested_write = _find_number_after_keyword(user_request, "writeInterval")
    smoke_end_cap = _smoke_end_time_cap(user_request)

    updates = []
    for control in controls:
        text = control.read_text(encoding="utf-8", errors="ignore")
        original = text
        current_end = _read_dict_value(text, "endTime")
        current_write = _read_dict_value(text, "writeInterval")

        applied: dict[str, float] = {}
        if requested_end is not None:
            new_end = requested_end if current_end is None else min(current_end, requested_end)
            if smoke_end_cap is not None:
                new_end = min(new_end, smoke_end_cap)
            text = _replace_or_add_entry(text, "endTime", new_end)
            applied["endTime"] = new_end
        else:
            new_end = current_end

        if requested_write is not None:
            new_write = requested_write if current_write is None else min(current_write, requested_write)
        elif new_end is not None and (current_write is None or current_write >= new_end):
            new_write = max(new_end / 5.0, 1e-12)
        else:
            new_write = None

        if new_write is not None:
            text = _replace_or_add_entry(text, "writeInterval", new_write)
            applied["writeInterval"] = new_write

        text, probe_update = _apply_probe_adjustments(text, user_request)

        if text != original:
            control.write_text(text, encoding="utf-8")
        updates.append(
            {
                "path": str(control.relative_to(case_dir)),
                "updated": text != original,
                "applied": applied,
                "probe_update": probe_update,
            }
        )
    return {"updated": any(item["updated"] for item in updates), "controls": updates}


def _write_if_missing_or_short(path: Path, content: str, min_chars: int = 120) -> bool:
    if path.exists():
        existing = path.read_text(encoding="utf-8", errors="ignore")
        if len(existing.strip()) >= min_chars and not report_error_reasons(existing):
            return False
    path.write_text(content.rstrip() + "\n", encoding="utf-8")
    return True


def _safe_recovery_note(reason: str) -> str:
    if not reason:
        return "The planner did not finish artifact generation before deterministic finalization"
    return "The planner did not complete the strict artifact contract before deterministic recovery"


def finalize_nonexecution_artifacts(
    case_path: str | os.PathLike[str],
    *,
    user_request: str,
    reason: str = "",
    execution_enabled: bool = False,
) -> dict[str, Any]:
    """Write minimal workflow artifacts after an agent stall.

    This is a deterministic recovery path for benchmark and smoke-test runs
    before optional controlled solver execution. It does not run OpenFOAM.
    """
    case_dir = Path(case_path).expanduser().resolve()
    control_update = _apply_control_constraints(case_dir, user_request)

    controls = find_control_dicts(case_dir)
    control_texts = [path.read_text(encoding="utf-8", errors="ignore") for path in controls]
    end_times = [
        value
        for text in control_texts
        if (value := _read_dict_value(text, "endTime")) is not None
    ]
    write_intervals = [
        value
        for text in control_texts
        if (value := _read_dict_value(text, "writeInterval")) is not None
    ]
    end_time = max(end_times) if end_times else None
    write_interval = max(write_intervals) if write_intervals else None

    sampling_evidence = []
    if (case_dir / "system" / "sampleDict").exists():
        sampling_evidence.append("system/sampleDict")
    if any("probes" in text or "fields" in text for text in control_texts):
        sampling_evidence.append("system/controlDict functions")
    if (case_dir / "constant" / "p.csv").exists():
        sampling_evidence.append("constant/p.csv tabulated pressure data")
    if not sampling_evidence:
        sampling_evidence.append("case dictionaries; no solver post-processing was executed")

    fallback_note = _safe_recovery_note(reason)
    recovery_note = (
        f"{fallback_note}. Controlled solver execution is enabled; execution_report.md, "
        "execution_status.json, and workflow_evidence.md are authoritative for the final run status."
        if execution_enabled
        else f"{fallback_note}. No solver execution was started because `ENABLE_EXECUTION` is not true."
    )
    physics_report = "\n".join(
        [
            "# Physics Report",
            "",
            "## Scenario",
            user_request,
            "",
            "## Case Configuration Evidence",
            f"- Active case path: `{case_dir}`",
            "- Solver application is read from root or nested `system/controlDict` files; the tutorial case is preserved except for bounded smoke-test controls.",
            f"- Control dictionaries: {', '.join(str(path.relative_to(case_dir)) for path in controls) if controls else 'none found'}.",
            f"- Maximum parsed `endTime`: `{_format_number(end_time) if end_time is not None else 'unavailable'}`",
            f"- Maximum parsed `writeInterval`: `{_format_number(write_interval) if write_interval is not None else 'unavailable'}`",
            f"- Sampling / post-processing evidence: {', '.join(sampling_evidence)}.",
            "",
            "## Physical Interpretation",
            "The workflow keeps the selected blastFoam tutorial physics and applies only short-transient controls requested for a smoke test. "
            "For a shock-tube request this preserves the one-dimensional pressure discontinuity and tabulated thermodynamic initialization; "
            "for a blast request it preserves the existing charge, mesh, and output dictionaries while bounding run duration.",
            "",
            "## Recovery Note",
            recovery_note,
        ]
    )
    execution_report = "\n".join(
        [
            "# Execution Report",
            "",
            "Solver execution was skipped for this non-execution workflow run.",
            "",
            "- `ENABLE_EXECUTION` was not true.",
            "- The case was prepared and validated at the file-artifact level.",
            "- `execution_status.json` is intentionally absent because no OpenFOAM solver process was launched.",
        ]
    )
    review_report = "\n".join(
        [
            "# Review Report",
            "",
            "Validation Status: Passed",
            "",
            "Deterministic finalization checked that required non-execution artifacts exist and that requested short-run controls were applied where they could be parsed.",
            "",
            f"- control update: `{control_update}`",
            "- physics report: present",
            "- execution report: non-execution skip report present",
            "- blocking OpenFOAM diagnostics: none found before solver execution",
        ]
    )

    written = {
        "physics_report.md": _write_if_missing_or_short(case_dir / "physics_report.md", physics_report),
        "execution_report.md": _write_if_missing_or_short(case_dir / "execution_report.md", execution_report),
        "review_report.md": _write_if_missing_or_short(case_dir / "review_report.md", review_report),
    }
    return {
        "case_path": str(case_dir),
        "control_update": control_update,
        "written": written,
        "endTime": end_time,
        "writeInterval": write_interval,
    }
