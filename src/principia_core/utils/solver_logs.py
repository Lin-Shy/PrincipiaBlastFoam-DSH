from __future__ import annotations

import os
import re
import shlex
from pathlib import Path
from typing import Iterable, Optional


UTILITY_APPLICATIONS = {
    "addEmptyPatch",
    "blastToVTK",
    "blockMesh",
    "calculateImpulse",
    "changeDictionary",
    "checkMesh",
    "createPatch",
    "decomposePar",
    "foamDictionary",
    "foamToVTK",
    "mapFields",
    "postProcess",
    "reconstructPar",
    "renumberMesh",
    "redistributePar",
    "rotateFields",
    "sample",
    "setExprFields",
    "setFields",
    "setRefinedFields",
    "snappyHexMesh",
    "surfaceFeatures",
    "topoSet",
    "transformPoints",
}


def _strip_cpp_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    return re.sub(r"//.*", "", text)


def _normalize_application(value: str) -> Optional[str]:
    token = value.strip().strip(";").strip("'\"")
    if not token:
        return None
    token = token.split()[0].strip("'\"")
    if token in {"$(getApplication)", "`getApplication`"}:
        return None
    if "$" in token or "`" in token:
        return None
    return os.path.basename(token)


def parse_control_application(case_path: str | Path) -> Optional[str]:
    control_dict = Path(case_path) / "system" / "controlDict"
    if not control_dict.exists():
        return None

    text = control_dict.read_text(encoding="utf-8", errors="ignore")
    clean_text = _strip_cpp_comments(text)
    match = re.search(r"(?m)^\s*application\s+([^;]+);", clean_text)
    if not match:
        return None
    return _normalize_application(match.group(1))


def _iter_allrun_applications(allrun_text: str, control_application: Optional[str]) -> Iterable[str]:
    clean_text = _strip_cpp_comments(allrun_text)
    for raw_line in clean_text.splitlines():
        line = raw_line.strip()
        if not line or "runApplication" not in line and "runParallel" not in line:
            continue
        try:
            tokens = shlex.split(line)
        except ValueError:
            continue

        for function_name in ("runApplication", "runParallel"):
            if function_name not in tokens:
                continue
            index = tokens.index(function_name) + 1
            while index < len(tokens):
                token = tokens[index]
                if token == "-s" and index + 2 < len(tokens):
                    index += 2
                    continue
                if token.startswith("-"):
                    index += 1
                    continue
                if token in {"$(getApplication)", "`getApplication`"} and control_application:
                    yield control_application
                else:
                    app = _normalize_application(token)
                    if app:
                        yield app
                break


def parse_allrun_solver_application(case_path: str | Path, control_application: Optional[str] = None) -> Optional[str]:
    allrun = Path(case_path) / "Allrun"
    if not allrun.exists():
        return None

    text = allrun.read_text(encoding="utf-8", errors="ignore")
    solver_application = None
    for application in _iter_allrun_applications(text, control_application):
        if application not in UTILITY_APPLICATIONS:
            solver_application = application
    return solver_application


def _ignored_log_path(case_dir: Path, log_path: Path) -> bool:
    try:
        relative_parts = log_path.relative_to(case_dir).parts
    except ValueError:
        return True
    return any(part.startswith("processor") or part.startswith(".") for part in relative_parts[:-1])


def iter_case_log_paths(case_path: str | Path, pattern: str = "log.*") -> list[Path]:
    case_dir = Path(case_path)
    if not case_dir.exists():
        return []

    paths: list[Path] = []
    seen: set[Path] = set()
    for log_path in sorted(case_dir.rglob(pattern)):
        if not log_path.is_file() or _ignored_log_path(case_dir, log_path):
            continue
        if log_path in seen:
            continue
        seen.add(log_path)
        paths.append(log_path)
    return paths


def _application_from_log_path(log_path: Path) -> str:
    return log_path.name.removeprefix("log.").split(".")[0]


def _application_log_paths(case_dir: Path, application: str) -> list[Path]:
    paths: list[Path] = []
    exact_name = f"log.{application}"
    for log_path in iter_case_log_paths(case_dir):
        if log_path.name == exact_name or log_path.name.startswith(f"{exact_name}."):
            paths.append(log_path)
    return paths


def resolve_solver_log_paths(case_path: str | Path) -> list[Path]:
    case_dir = Path(case_path)
    control_application = parse_control_application(case_dir)
    solver_application = control_application or parse_allrun_solver_application(case_dir, control_application)

    if solver_application:
        return _application_log_paths(case_dir, solver_application)

    candidates: list[Path] = []
    for log_path in iter_case_log_paths(case_dir):
        application = _application_from_log_path(log_path)
        if application and application not in UTILITY_APPLICATIONS:
            candidates.append(log_path)
    blastfoam_logs = [path for path in candidates if _application_from_log_path(path) == "blastFoam"]
    if blastfoam_logs:
        return blastfoam_logs
    return candidates


def solver_log_contains_clean_end(log_path: str | Path) -> bool:
    try:
        content = Path(log_path).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    return "\nEnd\n" in content or content.rstrip().endswith("End")


def solver_logs_missing_clean_end(case_path: str | Path) -> list[Path]:
    return [path for path in resolve_solver_log_paths(case_path) if not solver_log_contains_clean_end(path)]


def solver_log_has_clean_end(case_path: str | Path) -> bool:
    solver_logs = resolve_solver_log_paths(case_path)
    return bool(solver_logs) and not any(not solver_log_contains_clean_end(path) for path in solver_logs)
