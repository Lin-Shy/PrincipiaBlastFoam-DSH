from __future__ import annotations

import os
import pwd
import re
import shlex
import shutil
import subprocess
from pathlib import Path
from typing import Any, Dict, List


PARALLEL_RE = re.compile(r"(^|\s)(runParallel|mpirun|mpiexec)(\s|$)")
DYNAMIC_CODE_RE = re.compile(r"#\s*(calc|codeStream)\b|\bdynamicCode\b")
# OpenFOAM installations are host-specific.  Keep the portable package
# unconfigured by default and let deployments provide these paths explicitly.
DEFAULT_OPENFOAM_BASHRC = ""
DEFAULT_BLASTFOAM_BASHRC = ""


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def allrun_uses_parallel(case_path: str | os.PathLike[str] | None) -> bool:
    if not case_path:
        return False
    allrun = Path(case_path) / "Allrun"
    return bool(PARALLEL_RE.search(_read_text(allrun)))


def case_uses_dynamic_code(case_path: str | os.PathLike[str] | None) -> bool:
    if not case_path:
        return False
    root = Path(case_path)
    for relative_root in ("system", "constant", "0", "0.orig"):
        directory = root / relative_root
        if not directory.exists():
            continue
        for path in directory.rglob("*"):
            if path.is_file() and DYNAMIC_CODE_RE.search(_read_text(path)):
                return True
    return False


def configured_execution_user() -> str | None:
    user = os.getenv("OPENFOAM_EXECUTION_USER", "").strip()
    return user or None


def _execution_user_error(user: str | None) -> str | None:
    if not user:
        return None
    try:
        info = pwd.getpwnam(user)
    except KeyError:
        return f"OPENFOAM_EXECUTION_USER does not exist: {user}"
    if info.pw_uid == 0:
        return "OPENFOAM_EXECUTION_USER must not be root"
    return None


def _bool_env(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def _case_writable_by_user(case_dir: Path, user: str) -> bool:
    try:
        result = subprocess.run(
            ["su", "-s", "/bin/bash", user, "-c", f"test -w {shlex.quote(str(case_dir))}"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
        )
    except Exception:
        return False
    return result.returncode == 0


def _source_environment_command() -> str:
    parts: list[str] = []
    openfoam_bashrc = os.getenv("OPENFOAM_BASHRC", DEFAULT_OPENFOAM_BASHRC).strip()
    blastfoam_bashrc = os.getenv("BLASTFOAM_BASHRC", DEFAULT_BLASTFOAM_BASHRC).strip()
    if openfoam_bashrc:
        resolved = Path(openfoam_bashrc).expanduser()
        if resolved.is_file() and os.access(resolved, os.R_OK):
            parts.append(f"source {shlex.quote(str(resolved))} >/dev/null 2>&1")
    if blastfoam_bashrc:
        resolved = Path(blastfoam_bashrc).expanduser()
        if resolved.is_file() and os.access(resolved, os.R_OK):
            parts.append(f"MAKE=True source {shlex.quote(str(resolved))} >/dev/null 2>&1")
    return " && ".join(parts)


def _check_environment_scripts(blockers: List[str], warnings: List[str]) -> None:
    for env_name, default in (
        ("OPENFOAM_BASHRC", DEFAULT_OPENFOAM_BASHRC),
        ("BLASTFOAM_BASHRC", DEFAULT_BLASTFOAM_BASHRC),
    ):
        configured = os.getenv(env_name, default).strip()
        if not configured:
            warnings.append(
                f"{env_name} is not configured; relying on the current PATH/environment"
            )
            continue
        resolved = Path(configured).expanduser()
        if not resolved.is_file() or not os.access(resolved, os.R_OK):
            blockers.append(f"{env_name} does not point to a readable file: {resolved}")


def _commands_available_after_setup(commands: set[str], execution_user: str | None) -> set[str]:
    if not commands:
        return set()
    setup = _source_environment_command()
    command_list = " ".join(shlex.quote(command) for command in sorted(commands))
    shell_command = (
        (setup + " && " if setup else "")
        + f"for command in {command_list}; do command -v \"$command\" >/dev/null 2>&1 && echo \"$command\"; done"
    )
    args = ["bash", "-lc", shell_command]
    if os.geteuid() == 0 and execution_user:
        args = ["su", "-s", "/bin/bash", execution_user, "-c", shell_command]
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception:
        return set()
    return {line.strip() for line in result.stdout.splitlines() if line.strip()}


def _missing_case_commands(case_path: Path, execution_user: str | None) -> List[str]:
    allrun_text = _read_text(case_path / "Allrun")
    required: set[str] = set()
    for match in re.finditer(r"\b(?:runApplication|runParallel)\s+(?:-[A-Za-z]\s+\S+\s+)*([A-Za-z][A-Za-z0-9_.+-]*)", allrun_text):
        command = match.group(1)
        if command not in {"$(getApplication)", "getApplication"}:
            required.add(command)

    available = _commands_available_after_setup(required, execution_user)
    return [command for command in sorted(required) if command not in available and shutil.which(command) is None]


def run_execution_preflight(case_path: str | os.PathLike[str] | None) -> Dict[str, Any]:
    blockers: List[str] = []
    warnings: List[str] = []
    case_dir = Path(case_path or "")
    execution_user = configured_execution_user()
    user_error = _execution_user_error(execution_user)
    if user_error:
        blockers.append(user_error)
    _check_environment_scripts(blockers, warnings)

    if not case_path:
        blockers.append("case_path is not set")
    elif not case_dir.exists():
        blockers.append(f"case directory does not exist: {case_dir}")
    elif not (case_dir / "Allrun").exists():
        warnings.append("Allrun is missing; execution agent may need to create it")

    if case_path and allrun_uses_parallel(case_dir):
        if shutil.which("mpirun") is None and shutil.which("mpiexec") is None:
            blockers.append("Allrun uses parallel execution, but neither mpirun nor mpiexec is available")

    if case_path and os.geteuid() == 0 and case_uses_dynamic_code(case_dir):
        if execution_user:
            warnings.append(
                f"case uses OpenFOAM dynamic code; solver will run as OPENFOAM_EXECUTION_USER={execution_user}"
            )
        elif os.getenv("ALLOW_ROOT_OPENFOAM", "false").lower() not in {"1", "true", "yes", "on"}:
            blockers.append(
                "case uses OpenFOAM dynamic code (#calc/#codeStream), but execution is running as root"
            )

    if case_path and os.geteuid() == 0 and execution_user and case_dir.exists():
        if _bool_env("OPENFOAM_CHOWN_CASE", True):
            warnings.append(
                f"case ownership will be changed to OPENFOAM_EXECUTION_USER={execution_user} before execution"
            )
        elif not _case_writable_by_user(case_dir, execution_user):
            blockers.append(
                f"case directory is not writable by OPENFOAM_EXECUTION_USER={execution_user}; "
                "set OPENFOAM_CHOWN_CASE=true or adjust permissions"
            )

    if case_path and case_dir.exists():
        missing_commands = _missing_case_commands(case_dir, execution_user)
        if missing_commands:
            warnings.append(
                "OpenFOAM commands not found in PATH before execution: " + ", ".join(missing_commands)
            )

    return {
        "ok": not blockers,
        "blockers": blockers,
        "warnings": warnings,
        "execution_user": execution_user,
    }


def format_preflight_report(preflight: Dict[str, Any]) -> str:
    lines = ["Execution failed: environment preflight blocked execution.", ""]
    lines.append("Environment blockers:")
    for blocker in preflight.get("blockers") or []:
        lines.append(f"- {blocker}")
    warnings = preflight.get("warnings") or []
    if warnings:
        lines.extend(["", "Warnings:"])
        for warning in warnings:
            lines.append(f"- {warning}")
    lines.append("")
    lines.append("No solver command was started.")
    return "\n".join(lines)
