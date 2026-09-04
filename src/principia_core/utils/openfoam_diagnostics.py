from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, List, Optional

from principia_core.utils.solver_logs import iter_case_log_paths


FOAM_WARNING_RE = re.compile(r"FOAM Warning", re.IGNORECASE)
FOAM_FATAL_RE = re.compile(r"FOAM FATAL|FOAM exiting|segmentation fault|sigsegv", re.IGNORECASE)
MISSING_OBJECT_RE = re.compile(r"cannot find required object\s+([A-Za-z0-9_.+-]+)", re.IGNORECASE)
DYNAMIC_DERIVED_FIELDS = {"dynamicp", "dynamicpressure", "overpressure", "impulse"}


@dataclass(frozen=True)
class OpenFOAMDiagnostic:
    severity: str
    category: str
    blocking: bool
    source: str
    line: int
    message: str
    hint: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


def _context(lines: list[str], index: int, width: int = 8) -> str:
    start = max(0, index - 1)
    end = min(len(lines), index + width + 1)
    return "\n".join(line.strip() for line in lines[start:end] if line.strip())


def _classify_missing_object(message: str) -> tuple[str, str, bool, str]:
    match = MISSING_OBJECT_RE.search(message)
    object_name = match.group(1) if match else ""
    object_key = object_name.lower()
    if object_key in DYNAMIC_DERIVED_FIELDS:
        return (
            "nonblocking_warning",
            "derived_field_unavailable",
            False,
            (
                f"{object_name} is a derived/function-object field. Verify final field or "
                "postProcessing output before treating this as a run failure."
            ),
        )
    return (
        "warning",
        "missing_runtime_object",
        False,
        "A function object referenced a field/object that was not present at this log point.",
    )


def _classify_fatal_message(message: str) -> tuple[str, str]:
    lowered = message.lower()
    if "internal patch should be added" in lowered:
        return (
            "parallel_internal_patch_missing",
            "Dynamic mesh balancing needs an internal patch; addEmptyPatch must complete before blastFoam.",
        )
    if "expected a '('" in lowered or 'expected a "("' in lowered:
        return (
            "field_dictionary_type_mismatch",
            "A field dictionary value has the wrong scalar/vector syntax for its boundary condition.",
        )
    if "keyword gamma is undefined" in lowered:
        return (
            "boundary_condition_missing_entry",
            "A boundary-condition dictionary is missing a required entry.",
        )
    if "was not found in \"postprocessing/pressureprobes\"" in lowered:
        return (
            "postprocessing_missing_pressure_field",
            "calculateImpulse could not find the requested pressure field in pressureProbes output.",
        )
    return ("openfoam_fatal", "OpenFOAM reported a fatal runtime condition.")


def classify_openfoam_log_text(text: str, source: str = "") -> List[OpenFOAMDiagnostic]:
    """Return deterministic OpenFOAM diagnostics from log text.

    This intentionally does not decide pass/fail for the whole workflow. It only
    classifies log evidence so the harness can separate fatal solver failures
    from known nonblocking warnings.
    """
    diagnostics: List[OpenFOAMDiagnostic] = []
    lines = (text or "").splitlines()
    for index, line in enumerate(lines):
        line_number = index + 1
        if FOAM_FATAL_RE.search(line):
            message = _context(lines, index, width=5)[:1200]
            category, hint = _classify_fatal_message(message)
            diagnostics.append(
                OpenFOAMDiagnostic(
                    severity="fatal",
                    category=category,
                    blocking=True,
                    source=source,
                    line=line_number,
                    message=message,
                    hint=hint,
                )
            )
            continue

        if not FOAM_WARNING_RE.search(line):
            continue

        message = _context(lines, index, width=8)
        if MISSING_OBJECT_RE.search(message):
            severity, category, blocking, hint = _classify_missing_object(message)
        elif "undefined faces" in message.lower() and "default patch" in message.lower():
            severity = "nonblocking_warning"
            category = "mesh_default_patch"
            blocking = False
            hint = "blockMesh added undefined faces to the default patch; verify mesh quality if the solver later fails."
        elif "blastprobes::findelements" in message.lower() or "blastprobes were not found" in message.lower():
            severity = "nonblocking_warning"
            category = "probe_location_adjusted"
            blocking = False
            hint = "blastProbes moved requested probe locations to nearby patch faces; verify probe placement, but the run can continue."
        elif "boundary changed, proceed with care" in message.lower():
            severity = "nonblocking_warning"
            category = "mesh_boundary_update"
            blocking = False
            hint = "The mesh changed during sampling or adaptive updates; this is informational unless a later fatal error appears."
        elif "requested mass is" in message.lower() and "set mass is" in message.lower():
            severity = "warning"
            category = "charge_mass_discretization"
            blocking = False
            hint = "setRefinedFields could not match the requested charge mass on the available mesh; review physical fidelity."
        elif "libblastfunctionobject.so" in message.lower() and "could not load" in message.lower():
            severity = "warning"
            category = "blast_function_library_unavailable"
            blocking = False
            hint = "A blast function-object library was unavailable; verify requested post-processing outputs separately."
        elif "only cell interpolation can be applied" in message.lower():
            severity = "nonblocking_warning"
            category = "probe_interpolation_downgraded"
            blocking = False
            hint = "blastProbes fell back to cell interpolation; verify probe placement if quantitative sampling matters."
        else:
            severity = "warning"
            category = "openfoam_warning"
            blocking = False
            hint = "Review this warning in context; it is not fatal by itself."

        diagnostics.append(
            OpenFOAMDiagnostic(
                severity=severity,
                category=category,
                blocking=blocking,
                source=source,
                line=line_number,
                message=message[:1200],
                hint=hint,
            )
        )
    return diagnostics


def classify_openfoam_logs(paths: Iterable[Path]) -> List[OpenFOAMDiagnostic]:
    diagnostics: List[OpenFOAMDiagnostic] = []
    for path in paths:
        if not path.exists() or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        diagnostics.extend(classify_openfoam_log_text(text, source=str(path)))
    return diagnostics


def classify_case_openfoam_logs(case_path: str | Path, extra_logs: Optional[Iterable[Path]] = None) -> List[dict]:
    case_dir = Path(case_path)
    paths = iter_case_log_paths(case_dir) if case_dir.exists() else []
    if extra_logs:
        paths.extend(Path(path) for path in extra_logs)
    return [diagnostic.to_dict() for diagnostic in classify_openfoam_logs(paths)]


def summarize_diagnostics(diagnostics: Iterable[dict]) -> dict:
    summary = {
        "fatal": 0,
        "error": 0,
        "warning": 0,
        "nonblocking_warning": 0,
        "blocking": 0,
    }
    categories: dict[str, int] = {}
    for diagnostic in diagnostics:
        severity = str(diagnostic.get("severity") or "warning")
        if severity not in summary:
            summary[severity] = 0
        summary[severity] += 1
        if diagnostic.get("blocking"):
            summary["blocking"] += 1
        category = str(diagnostic.get("category") or "unknown")
        categories[category] = categories.get(category, 0) + 1
    summary["categories"] = categories
    return summary
