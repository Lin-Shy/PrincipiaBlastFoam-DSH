from __future__ import annotations

import json
import os
import pwd
import signal
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from principia_core.tutorials import TutorialInitializer
from principia_core.utils.case_digest import build_physics_case_digest
from principia_core.utils.execution_preflight import (
    DEFAULT_BLASTFOAM_BASHRC,
    DEFAULT_OPENFOAM_BASHRC,
    format_preflight_report,
    run_execution_preflight,
)
from principia_core.utils.execution_status import (
    build_execution_status,
    read_execution_status,
    write_execution_status,
)
from principia_core.utils.fallback_finalize import finalize_nonexecution_artifacts
from principia_core.utils.openfoam_diagnostics import classify_case_openfoam_logs, summarize_diagnostics
from principia_core.utils.postprocessing_report import write_post_processing_report as write_post_processing_report_file
from principia_core.utils.review_report import read_review_validation_status, write_deterministic_review_report
from principia_core.utils.workflow_artifacts import validate_workflow_artifacts, write_artifact_contract
from principia_core.utils.workflow_evidence import write_workflow_evidence


def _json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


def _is_empty_case(case_path: Path) -> bool:
    if not case_path.exists():
        return True
    return not any(child.name and not child.name.startswith(".") for child in case_path.iterdir())


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def _configured_execution_user() -> str | None:
    user = os.getenv("OPENFOAM_EXECUTION_USER", "").strip()
    return user or None


def _prepare_case_for_execution_user(case_dir: Path, execution_user: str | None) -> dict[str, Any]:
    if os.geteuid() != 0 or not execution_user:
        return {"changed_owner": False, "execution_user": execution_user}

    user_info = pwd.getpwnam(execution_user)
    if user_info.pw_uid == 0:
        raise ValueError("OPENFOAM_EXECUTION_USER must not be root")

    if not _bool_env("OPENFOAM_CHOWN_CASE", True):
        return {"changed_owner": False, "execution_user": execution_user}

    os.chown(case_dir, user_info.pw_uid, user_info.pw_gid)
    for path in case_dir.rglob("*"):
        try:
            os.chown(path, user_info.pw_uid, user_info.pw_gid)
        except FileNotFoundError:
            continue
    return {"changed_owner": True, "execution_user": execution_user}


def _build_allrun_shell_command(case_dir: Path) -> str:
    openfoam_bashrc = os.getenv("OPENFOAM_BASHRC", DEFAULT_OPENFOAM_BASHRC).strip()
    blastfoam_bashrc = os.getenv("BLASTFOAM_BASHRC", DEFAULT_BLASTFOAM_BASHRC).strip()
    setup_parts: list[str] = []
    if openfoam_bashrc:
        resolved = Path(openfoam_bashrc).expanduser()
        if resolved.is_file() and os.access(resolved, os.R_OK):
            setup_parts.append(f"source {shlex.quote(str(resolved))} >/dev/null 2>&1")
    if blastfoam_bashrc:
        resolved = Path(blastfoam_bashrc).expanduser()
        if resolved.is_file() and os.access(resolved, os.R_OK):
            setup_parts.append(f"MAKE=True source {shlex.quote(str(resolved))} >/dev/null 2>&1")
    setup_parts.append(f"cd {shlex.quote(str(case_dir))}")
    setup_parts.append("./Allrun")
    return " && ".join(setup_parts)


def _execution_subprocess_args(case_dir: Path, shell_command: str, execution_user: str | None) -> tuple[list[str], Path]:
    if os.geteuid() == 0 and execution_user:
        return ["su", "-s", "/bin/bash", execution_user, "-c", shell_command], Path("/")
    return ["bash", "-lc", shell_command], case_dir


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _resolve_execution_timeout_seconds(requested_timeout_seconds: int) -> int:
    configured_timeout = _int_env("PRINCIPIA_EXECUTION_TIMEOUT_SECONDS", 180)
    min_timeout = _int_env("PRINCIPIA_MIN_EXECUTION_TIMEOUT_SECONDS", configured_timeout)
    requested = max(1, int(requested_timeout_seconds))
    return max(min_timeout, min(requested, 24 * 3600))


def _communicate_with_timeout(
    args: list[str],
    *,
    cwd: Path,
    timeout_seconds: int,
) -> tuple[int | None, str, bool]:
    process = subprocess.Popen(
        args,
        cwd=cwd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            stdout, stderr = process.communicate(timeout=20)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            stdout, stderr = process.communicate()
        timeout_output = (exc.output or "") if isinstance(exc.output, str) else ""
        timeout_error = (exc.stderr or "") if isinstance(exc.stderr, str) else ""
        stdout = (timeout_output + "\n" + (stdout or "")).strip()
        stderr = (timeout_error + "\n" + (stderr or "")).strip()
    return process.returncode, (stdout or "") + ("\nSTDERR:\n" + stderr if stderr else ""), timed_out


def initialize_case_from_tutorial(
    *,
    case_path: str | os.PathLike[str],
    user_request: str,
    tutorial_path: str | os.PathLike[str],
    force: bool = False,
) -> dict[str, Any]:
    """Initialize a case directory from the best matching blastFoam tutorial."""
    target = Path(case_path).expanduser().resolve()
    tutorials = Path(tutorial_path).expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)

    if not force and not _is_empty_case(target):
        return {
            "initialized": False,
            "skipped": True,
            "message": f"Case directory is not empty: {target}",
            "case_path": str(target),
        }
    if not tutorials.exists():
        return {
            "initialized": False,
            "skipped": False,
            "message": f"Tutorial path does not exist: {tutorials}",
            "case_path": str(target),
        }

    initializer = TutorialInitializer(llm=None)
    cases = initializer.find_complete_cases(str(tutorials))
    selected = initializer.find_relevant_tutorial_cases(user_request, cases, top_k=1)
    if not selected:
        return {
            "initialized": False,
            "skipped": False,
            "message": "No relevant tutorial case found.",
            "case_path": str(target),
        }

    selected_case = selected[0]
    source_path = selected_case.get("path")
    success = bool(source_path and initializer.copy_case_files(source_path, str(target)))
    return {
        "initialized": success,
        "skipped": False,
        "message": (
            f"Initialized from {selected_case.get('relative_path')}"
            if success
            else f"Failed to copy tutorial case from {source_path}"
        ),
        "case_path": str(target),
        "tutorial_case_path": selected_case.get("relative_path"),
        "tutorial_source_path": source_path,
    }


def run_openfoam_case_once(
    case_path: str | os.PathLike[str],
    *,
    timeout_seconds: int = 3600,
) -> dict[str, Any]:
    """Run a prepared OpenFOAM case once and write execution artifacts."""
    case_dir = Path(case_path).expanduser().resolve()
    if not _bool_env("ENABLE_EXECUTION", True):
        return {
            "started": False,
            "blocked": True,
            "reason": "ENABLE_EXECUTION is explicitly false; solver was not started.",
        }

    preflight = run_execution_preflight(case_dir)
    if not preflight["ok"]:
        report = format_preflight_report(preflight)
        (case_dir / "execution_report.md").write_text(report, encoding="utf-8")
        status = build_execution_status(case_dir, report, "failed")
        status.update(
            {
                "status_source": "environment_preflight",
                "status_reason": "; ".join(preflight["blockers"]),
                "environment_status": "blocked",
                "environment_blockers": preflight["blockers"],
                "environment_warnings": preflight["warnings"],
                "execution_user": preflight.get("execution_user") or "current",
            }
        )
        write_execution_status(case_dir, status)
        write_workflow_evidence(case_dir)
        return {"started": False, "blocked": True, "preflight": preflight, "status": status}

    execution_user = _configured_execution_user()
    ownership = _prepare_case_for_execution_user(case_dir, execution_user)
    command = _build_allrun_shell_command(case_dir)
    subprocess_args, subprocess_cwd = _execution_subprocess_args(case_dir, command, execution_user)

    timeout_seconds = _resolve_execution_timeout_seconds(timeout_seconds)
    return_code, output, timed_out = _communicate_with_timeout(
        subprocess_args,
        cwd=subprocess_cwd,
        timeout_seconds=timeout_seconds,
    )
    if len(output) > 20000:
        output = output[-20000:]

    provisional_status = "completed" if return_code == 0 and not timed_out else "failed"
    status = build_execution_status(case_dir, output, provisional_status)
    status.update(
        {
            "return_code": return_code,
            "timed_out": timed_out,
            "timeout_seconds": timeout_seconds,
            "execution_user": execution_user or "current",
            "ownership_preparation": ownership,
        }
    )
    if timed_out:
        status.update(
            {
                "run_status": "failed",
                "final_status": "failed",
                "status_source": "execution_timeout",
                "status_reason": f"OpenFOAM execution exceeded timeout_seconds={timeout_seconds}.",
            }
        )
    write_execution_status(case_dir, status)
    evidence = write_workflow_evidence(case_dir)

    report = "\n".join(
        [
            "# Execution Report",
            "",
            f"- Command: `./Allrun`",
            f"- Execution user: `{execution_user or 'current'}`",
            f"- Case ownership changed before execution: `{ownership.get('changed_owner')}`",
            f"- Return code: `{return_code}`",
            f"- Timed out: `{timed_out}`",
            f"- Timeout seconds: `{timeout_seconds}`",
            f"- Run status: `{status.get('run_status')}`",
            f"- Final status: `{status.get('final_status')}`",
            f"- Status reason: {status.get('status_reason')}",
            "",
            "## Output Tail",
            "```text",
            output[-8000:],
            "```",
            "",
            "## Evidence",
            "- `execution_status.json` is the authoritative execution status.",
            "- `workflow_evidence.md` contains solver log and artifact evidence.",
        ]
    )
    (case_dir / "execution_report.md").write_text(report.rstrip() + "\n", encoding="utf-8")
    return {
        "started": True,
        "return_code": return_code,
        "timed_out": timed_out,
        "timeout_seconds": timeout_seconds,
        "status": status,
        "evidence": evidence,
    }


def complete_workflow_once(
    case_path: str | os.PathLike[str],
    *,
    user_request: str,
    require_execution: bool = True,
    require_review: bool = False,
    timeout_seconds: int = 3600,
) -> dict[str, Any]:
    """Complete deterministic workflow artifacts for a prepared case."""
    case_dir = Path(case_path).expanduser().resolve()
    execution_gate_enabled = _bool_env("ENABLE_EXECUTION", True)
    finalization = finalize_nonexecution_artifacts(
        case_dir,
        user_request=user_request,
        reason="complete_workflow deterministic domain tool",
        execution_enabled=require_execution and execution_gate_enabled,
    )

    execution: dict[str, Any] | None = None
    if require_execution:
        execution = run_openfoam_case_once(case_dir, timeout_seconds=timeout_seconds)

    post_processing = write_post_processing_report_file(case_dir)

    review: dict[str, Any] | None = None
    if require_review or require_execution:
        review = write_deterministic_review_report(
            case_dir,
            require_execution=require_execution,
            reason="complete_workflow wrote deterministic review evidence.",
        )

    evidence = write_workflow_evidence(case_dir)
    state = {
        "execution_status": read_execution_status(case_dir),
        "validation_status": read_review_validation_status(case_dir),
    }
    contract = validate_workflow_artifacts(
        case_dir,
        state,
        require_execution=require_execution,
        require_review=require_review or require_execution,
    )
    path = write_artifact_contract(case_dir, contract)
    return {
        "case_path": str(case_dir),
        "finalization": finalization,
        "execution": execution,
        "post_processing": post_processing,
        "review": review,
        "evidence_created_at": evidence.get("created_at"),
        "artifact_contract_path": str(path),
        "artifact_contract_ok": contract["ok"],
        "issues": contract["issues"],
        "terminal_success": bool(contract["ok"]),
        "next_action": (
            "Stop tool use and provide the final answer."
            if contract["ok"]
            else "Fix the listed issues, then call complete_workflow or validate_artifacts again."
        ),
    }


@dataclass(frozen=True)
class OpenFOAMDomainService:
    """Bound, framework-independent API for one blastFoam/OpenFOAM case.

    DSH plugins and MCP adapters should wrap these methods instead of importing
    LangChain tool objects. Methods return JSON-serializable dictionaries.
    """

    case_path: str | os.PathLike[str]
    user_request: str
    tutorial_path: str | os.PathLike[str]
    require_execution: bool = True
    require_review: bool = False

    @property
    def case_dir(self) -> Path:
        return Path(self.case_path).expanduser().resolve()

    def initialize_case(self, force: bool = False) -> dict[str, Any]:
        return initialize_case_from_tutorial(
            case_path=self.case_dir,
            user_request=self.user_request,
            tutorial_path=self.tutorial_path,
            force=force,
        )

    def case_digest(self) -> dict[str, Any]:
        return build_physics_case_digest(self.case_dir, user_request=self.user_request)

    def execution_preflight(self) -> dict[str, Any]:
        return run_execution_preflight(self.case_dir)

    def run_case(self, timeout_seconds: int = 3600) -> dict[str, Any]:
        execution_gate_enabled = _bool_env("ENABLE_EXECUTION", True)
        finalize_nonexecution_artifacts(
            self.case_dir,
            user_request=self.user_request,
            reason="run_case pre-execution deterministic control finalization",
            execution_enabled=execution_gate_enabled,
        )
        result = run_openfoam_case_once(self.case_dir, timeout_seconds=timeout_seconds)
        result["post_processing"] = write_post_processing_report_file(self.case_dir)
        return result

    def complete(self, timeout_seconds: int = 3600) -> dict[str, Any]:
        return complete_workflow_once(
            self.case_dir,
            user_request=self.user_request,
            require_execution=self.require_execution,
            require_review=self.require_review,
            timeout_seconds=timeout_seconds,
        )

    def write_evidence(self) -> dict[str, Any]:
        return write_workflow_evidence(self.case_dir)

    def write_post_processing_report(self) -> dict[str, Any]:
        return write_post_processing_report_file(self.case_dir)

    def validate_artifacts(
        self,
        require_execution: bool | None = None,
        require_review: bool | None = None,
    ) -> dict[str, Any]:
        execution_required = self.require_execution if require_execution is None else require_execution
        review_required = self.require_review if require_review is None else require_review
        state = {
            "execution_status": read_execution_status(self.case_dir),
            "validation_status": read_review_validation_status(self.case_dir),
        }
        contract = validate_workflow_artifacts(
            self.case_dir,
            state,
            require_execution=execution_required,
            require_review=review_required,
        )
        contract["artifact_contract_path"] = str(write_artifact_contract(self.case_dir, contract))
        return contract

    def diagnostics(self) -> dict[str, Any]:
        diagnostics = classify_case_openfoam_logs(self.case_dir)
        return {"summary": summarize_diagnostics(diagnostics), "diagnostics": diagnostics[:50]}


def make_openfoam_tools(
    *,
    case_path: str | os.PathLike[str],
    user_request: str,
    tutorial_path: str | os.PathLike[str],
    default_require_execution: bool = True,
    default_require_review: bool = False,
):
    """Return plain callables for legacy adapters; no agent framework required."""
    case_dir = Path(case_path).expanduser().resolve()
    tutorial_dir = Path(tutorial_path).expanduser().resolve()

    def initialize_case(force: bool = False) -> str:
        """Initialize the active case from the most relevant blastFoam tutorial if the case is empty."""
        return _json(
            initialize_case_from_tutorial(
                case_path=case_dir,
                user_request=user_request,
                tutorial_path=tutorial_dir,
                force=force,
            )
        )

    def case_digest() -> str:
        """Return a deterministic bounded digest of the active OpenFOAM case configuration."""
        digest = build_physics_case_digest(case_dir, user_request=user_request)
        return digest["markdown"]

    def execution_preflight() -> str:
        """Check whether the active case can safely start OpenFOAM/blastFoam execution."""
        preflight = run_execution_preflight(case_dir)
        return _json(preflight)

    def run_openfoam_case(timeout_seconds: int = 3600) -> str:
        """Run the active case Allrun script when ENABLE_EXECUTION is true, then write execution artifacts."""
        finalize_nonexecution_artifacts(
            case_dir,
            user_request=user_request,
            reason="run_openfoam_case pre-execution deterministic control finalization",
            execution_enabled=_bool_env("ENABLE_EXECUTION", True),
        )
        result = run_openfoam_case_once(case_dir, timeout_seconds=timeout_seconds)
        result["post_processing"] = write_post_processing_report_file(case_dir)
        return _json(result)

    def complete_workflow(timeout_seconds: int = 3600) -> str:
        """Apply bounded case controls, run execution if required, write evidence/review, and validate artifacts."""
        return _json(
            complete_workflow_once(
                case_dir,
                user_request=user_request,
                require_execution=default_require_execution,
                require_review=default_require_review,
                timeout_seconds=timeout_seconds,
            )
        )

    def write_evidence() -> str:
        """Write workflow_evidence.md/json for the active case and return the evidence summary."""
        return _json(write_workflow_evidence(case_dir))

    def write_post_processing_report() -> str:
        """Write a deterministic post_processing_report.md summarizing available solver outputs."""
        return _json(write_post_processing_report_file(case_dir))

    def validate_artifacts(
        require_execution: bool = default_require_execution,
        require_review: bool = default_require_review,
    ) -> str:
        """Validate required workflow artifacts and write artifact_contract.json.

        Defaults follow the active runtime mode. In solver-enabled runs, calling
        this tool without arguments performs the strict execution/review check.
        """
        state = {
            "execution_status": read_execution_status(case_dir),
            "validation_status": read_review_validation_status(case_dir),
        }
        contract = validate_workflow_artifacts(
            case_dir,
            state,
            require_execution=require_execution,
            require_review=require_review,
        )
        path = write_artifact_contract(case_dir, contract)
        contract["artifact_contract_path"] = str(path)
        contract["terminal_success"] = bool(contract["ok"])
        contract["next_action"] = (
            "Stop tool use and provide the final answer."
            if contract["ok"]
            else "Fix the listed issues, then call validate_artifacts again."
        )
        return _json(contract)

    def openfoam_diagnostics() -> str:
        """Classify OpenFOAM log diagnostics in the active case."""
        diagnostics = classify_case_openfoam_logs(case_dir)
        return _json({"summary": summarize_diagnostics(diagnostics), "diagnostics": diagnostics[:50]})

    return [
        initialize_case,
        case_digest,
        execution_preflight,
        run_openfoam_case,
        complete_workflow,
        write_evidence,
        write_post_processing_report,
        validate_artifacts,
        openfoam_diagnostics,
    ]
