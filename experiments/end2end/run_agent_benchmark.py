#!/usr/bin/env python3
"""第 3 章端到端 benchmark 的 DeepSeek Harness 适配器。

既有第 3 章评测脚本调用这个历史文件名，并读取
``run_*/benchmark_report.json``。本模块保持该边界稳定，同时把旧应用 CLI
替换为 DSH headless CLI。

``--dry-run`` 有意保持低副作用：只创建 benchmark 报告目录并构造准确的
DSH 命令，不启动 DSH 或 OpenFOAM 进程。
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[2]
WORKSPACE_ROOT = PROJECT_ROOT.parents[1]
DEFAULT_DSH_BIN = Path(
    os.environ.get("PRINCIPIA_DSH_BIN", WORKSPACE_ROOT / "deepseek-harness" / "apps" / "cli" / "lib" / "bin.js")
)
DEFAULT_DSH_HOME = Path(os.environ.get("DSH_HOME", WORKSPACE_ROOT / "dsh-home"))
DEFAULT_TUTORIALS = Path(
    os.environ.get("BLASTFOAM_TUTORIALS", PROJECT_ROOT.parent / "blastFoam_tutorials")
)
DEFAULT_OUTPUT_ROOT = (
    PROJECT_ROOT.parent
    / "graduation-experiment-results"
    / "chapter3_end_to_end_evaluation"
    / "results"
    / "dsh_adapter_runs"
)
COMPLETION_MARKER = "PRINCIPIA_BENCHMARK_COMPLETE"
REPORT_NAMES = (
    "physics_report.md",
    "execution_report.md",
    "execution_status.json",
    "workflow_evidence.md",
    "artifact_contract.json",
    "review_report.md",
    "post_processing_report.md",
    "final_summary.md",
    "metrics_report.json",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def run_id_now() -> str:
    return datetime.now(timezone.utc).strftime("run_%Y%m%d_%H%M%S_%f")


def safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip()).strip("._")
    return cleaned or "case"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_cases(path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    document = read_json(path)
    if isinstance(document, list):
        metadata: dict[str, Any] = {"name": path.stem}
        raw_cases = document
    elif isinstance(document, dict):
        metadata = {key: value for key, value in document.items() if key not in {"cases", "tasks"}}
        raw_cases = document.get("cases", document.get("tasks"))
    else:
        raise ValueError("benchmark file must be a JSON object or array")

    if not isinstance(raw_cases, list):
        raise ValueError("benchmark JSON must contain a 'cases' or 'tasks' array")

    cases: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw_case in enumerate(raw_cases):
        if not isinstance(raw_case, dict):
            raise ValueError(f"case {index} must be an object")
        case = dict(raw_case)
        case_id = str(case.get("id") or case.get("case_id") or f"case_{index + 1}")
        if case_id in seen:
            raise ValueError(f"duplicate case id: {case_id}")
        seen.add(case_id)
        case["id"] = case_id
        cases.append(case)
    return metadata, cases


def select_cases(
    cases: Sequence[dict[str, Any]], case_ids: Sequence[str], limit: int | None
) -> list[dict[str, Any]]:
    selected = list(cases)
    if case_ids:
        requested = set(case_ids)
        available = {str(case["id"]) for case in cases}
        unknown = sorted(requested - available)
        if unknown:
            raise ValueError("unknown case id(s): " + ", ".join(unknown))
        selected = [case for case in cases if str(case["id"]) in requested]
    if limit is not None:
        if limit < 0:
            raise ValueError("--limit must be non-negative")
        selected = selected[:limit]
    return selected


def build_case_prompt(
    case: dict[str, Any],
    case_path: Path,
    tutorials_path: Path,
    *,
    execution_enabled: bool,
) -> str:
    case_id = str(case["id"])
    request = str(case.get("user_request") or case.get("prompt") or case.get("title") or "")
    expected = json.dumps(case.get("expected", {}), ensure_ascii=False, indent=2, sort_keys=True)
    execution_text = (
        "Execution is explicitly enabled. Use the MCP execution tools only after validation."
        if execution_enabled
        else "Execution is disabled. Do not invoke blastFoam, Allrun, OpenFOAM utilities, or any solver process."
    )
    artifact_text = (
        "Execution artifacts are required and must be backed by filesystem and solver-log evidence."
        if execution_enabled
        else "State clearly when an artifact is not applicable because execution is disabled."
    )
    return f"""You are running controlled Chapter 3 benchmark case {case_id!r}.

Use the project skill `blastfoam-workflow` and its specialist subagents. Work in this exact case directory:
{case_path}

Available blastFoam tutorials are rooted at:
{tutorials_path}

User request:
{request}

Expected machine-readable constraints (evaluation hints, not permission to fabricate evidence):
{expected}

Required procedure:
1. Select the closest tutorial and record the selected tutorial path in the workflow evidence.
2. Perform physics analysis and the smallest requested case configuration changes.
3. Validate dictionaries and generated artifacts using deterministic MCP/domain tools.
4. {execution_text}
5. Finalize all applicable standard artifacts: physics_report.md, execution_report.md,
   execution_status.json, workflow_evidence.md, artifact_contract.json, review_report.md,
   and post_processing_report.md. {artifact_text}
6. Do not claim a solver run, time directory, or clean solver end without filesystem evidence.

End the final response with exactly:
{COMPLETION_MARKER} case_id={case_id}
"""


def build_dsh_command(
    dsh_bin: Path,
    profile: str,
    prompt: str,
    patches: Iterable[Path] = (),
) -> list[str]:
    command = [str(dsh_bin), "--profile", profile]
    for patch in patches:
        command.extend(["--patch", str(patch)])
    command.append(prompt)
    return command


def build_child_environment(
    *,
    dsh_home: Path,
    case_root: Path,
    tutorials_path: Path,
    execution_enabled: bool,
    api_key_file: Path | None,
    run_as_user: str | None,
) -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        {
            "DSH_HOME": str(dsh_home),
            "PRINCIPIA_PROJECT_ROOT": str(PROJECT_ROOT),
            "PRINCIPIA_PYTHON": sys.executable,
            "PRINCIPIA_CASE_ROOT": str(case_root),
            "BLASTFOAM_TUTORIALS": str(tutorials_path),
            "ENABLE_EXECUTION": "true" if execution_enabled else "false",
            "REQUIRE_EXECUTION": "true" if execution_enabled else "false",
            "DSH_TELEMETRY_MODE": environment.get("DSH_TELEMETRY_MODE", "DISABLED"),
        }
    )
    if run_as_user:
        environment["OPENFOAM_EXECUTION_USER"] = run_as_user
    if api_key_file is not None:
        key = api_key_file.read_text(encoding="utf-8").strip()
        if not key:
            raise ValueError(f"API key file is empty: {api_key_file}")
        environment["DEEPSEEK_API_KEY"] = key
    return environment


def public_command(command: Sequence[str]) -> list[str]:
    """Return a report-safe command without embedding the potentially long prompt."""
    if not command:
        return []
    return [*command[:-1], "<benchmark-prompt>"]


def run_command(
    command: Sequence[str],
    *,
    cwd: Path,
    environment: dict[str, str],
    timeout_seconds: float,
    log_path: Path,
) -> dict[str, Any]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    timed_out = False
    with log_path.open("w", encoding="utf-8") as log:
        log.write("$ " + shlex.join(public_command(command)) + "\n")
        log.flush()
        process = subprocess.Popen(
            list(command),
            cwd=cwd,
            env=environment,
            stdout=log,
            stderr=subprocess.STDOUT,
            text=True,
            start_new_session=True,
        )
        try:
            exit_code = process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            timed_out = True
            os.killpg(process.pid, signal.SIGTERM)
            try:
                exit_code = process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                exit_code = process.wait()
    return {
        "exit_code": exit_code,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "timed_out": timed_out,
        "dry_run": False,
        "command": public_command(command),
    }


def _read_optional_json(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        value = read_json(path)
    except (OSError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _parse_end_time(control_dict: Path) -> float | None:
    if not control_dict.is_file():
        return None
    text = control_dict.read_text(encoding="utf-8", errors="ignore")
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"//.*", "", text)
    match = re.search(r"(?m)^\s*endTime\s+([^;\s]+)\s*;", text)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


def _configured_end_times(case_path: Path) -> list[dict[str, Any]]:
    if not case_path.exists():
        return []
    records: list[dict[str, Any]] = []
    for control_dict in sorted(case_path.rglob("controlDict")):
        if control_dict.parent.name != "system":
            continue
        value = _parse_end_time(control_dict)
        if value is not None:
            records.append({"path": str(control_dict.relative_to(case_path)), "end_time": value})
    return records


def _selected_tutorial(log_text: str, case_path: Path) -> str | None:
    evidence = _read_optional_json(case_path / "workflow_evidence.json")
    if evidence:
        for key in ("selected_tutorial", "tutorial_path", "tutorial_case_path"):
            if evidence.get(key):
                return str(evidence[key])
    patterns = (
        r"(?im)^\s*(?:selected[_ ]tutorial|tutorial_case_path)\s*[:=]\s*[`\"']?([^`\"'\r\n]+)",
        r"(?im)initialized\s+from\s+[`\"']?([^`\"'\r\n]+)",
    )
    for pattern in patterns:
        match = re.search(pattern, log_text)
        if match:
            return match.group(1).strip()
    return None


def collect_summary(
    case: dict[str, Any],
    case_path: Path,
    log_path: Path,
    *,
    execution_enabled: bool,
) -> dict[str, Any]:
    # Imported lazily so command construction/dry-run remains useful even if
    # the project package has not yet been installed into the interpreter.
    from principia_core.utils.openfoam_diagnostics import (
        classify_case_openfoam_logs,
        summarize_diagnostics,
    )
    from principia_core.utils.solver_logs import solver_log_has_clean_end
    from principia_core.utils.time_dirs import discover_numeric_time_dirs, unique_numeric_time_values

    log_text = log_path.read_text(encoding="utf-8", errors="ignore") if log_path.is_file() else ""
    reports = {name: (case_path / name).is_file() for name in REPORT_NAMES}
    contract = _read_optional_json(case_path / "artifact_contract.json")
    execution_status = _read_optional_json(case_path / "execution_status.json")
    time_locations = discover_numeric_time_dirs(case_path)
    time_values = unique_numeric_time_values(time_locations)
    end_times = _configured_end_times(case_path)
    diagnostics = classify_case_openfoam_logs(case_path, [log_path] if log_path.is_file() else None)
    diagnostics_summary = summarize_diagnostics(diagnostics)
    selected_tutorial = _selected_tutorial(log_text, case_path)

    expected = case.get("expected") if isinstance(case.get("expected"), dict) else {}
    required_reports = expected.get("required_reports") or ["physics_report.md"]
    preferred_keywords = [str(value).lower() for value in expected.get("preferred_case_keywords", [])]
    tutorial_text = (selected_tutorial or "").lower()
    status_completed = bool(
        execution_status
        and (
            execution_status.get("success") is True
            or execution_status.get("completed") is True
            or str(execution_status.get("status", "")).lower() in {"completed", "success", "succeeded"}
        )
    )
    checks = {
        "required_reports_present": all(reports.get(str(name), False) for name in required_reports),
        "physics_report_present": reports["physics_report.md"],
        "execution_report_present": reports["execution_report.md"],
        "execution_status_present": reports["execution_status.json"],
        "execution_status_completed": status_completed,
        "solver_log_has_end": solver_log_has_clean_end(case_path),
        "workflow_log_has_completion_marker": f"{COMPLETION_MARKER} case_id={case['id']}" in log_text,
        "workflow_failure_absent": not bool(re.search(r"(?im)(traceback|uncaught|workflow failed)", log_text)),
        "selected_tutorial_matches_expected": (
            bool(selected_tutorial)
            and (not preferred_keywords or any(keyword in tutorial_text for keyword in preferred_keywords))
        ),
        "case_selection_error_absent": "case selection error" not in log_text.lower(),
        "orchestrator_empty_output_absent": bool(log_text.strip()),
        "openfoam_blocking_diagnostics_absent": diagnostics_summary.get("blocking", 0) == 0,
        "artifact_contract_ok": bool(contract and contract.get("ok") is True),
    }
    return {
        "case_path": str(case_path),
        "log_path": str(log_path),
        "selected_tutorial": selected_tutorial,
        "reports": reports,
        "configured_end_time": end_times[0]["end_time"] if end_times else None,
        "configured_end_times": end_times,
        "time_dir_count": len(time_values),
        "time_dir_locations": time_locations,
        "post_processing_present": reports["post_processing_report.md"],
        "metrics_report": str(case_path / "metrics_report.json") if reports["metrics_report.json"] else None,
        "metrics_summary": _read_optional_json(case_path / "metrics_report.json"),
        "execution_status": execution_status,
        "artifact_contract": contract,
        "openfoam_diagnostics": diagnostics,
        "openfoam_diagnostic_summary": diagnostics_summary,
        "openfoam_diagnostics_total": len(diagnostics),
        "execution_enabled": execution_enabled,
        "checks": checks,
    }


def result_passed(run: dict[str, Any], summary: dict[str, Any], execution_enabled: bool) -> bool:
    if run.get("dry_run") or run.get("timed_out") or run.get("exit_code") != 0:
        return False
    checks = summary["checks"]
    required = (
        "required_reports_present",
        "physics_report_present",
        "workflow_log_has_completion_marker",
        "workflow_failure_absent",
        "selected_tutorial_matches_expected",
        "case_selection_error_absent",
        "orchestrator_empty_output_absent",
        "openfoam_blocking_diagnostics_absent",
        "artifact_contract_ok",
    )
    if not all(checks.get(name, False) for name in required):
        return False
    if execution_enabled:
        return bool(
            checks.get("execution_report_present")
            and checks.get("execution_status_present")
            and checks.get("execution_status_completed")
            and checks.get("solver_log_has_end")
        )
    return True


def aggregate_results(results: Sequence[dict[str, Any]]) -> dict[str, Any]:
    total = len(results)
    passed = sum(bool(item.get("benchmark_passed")) for item in results)
    return {
        "cases_total": total,
        "cases_executed": sum(not item["run"].get("dry_run", False) for item in results),
        "exit_code_zero": sum(item["run"].get("exit_code") == 0 for item in results),
        "timed_out": sum(bool(item["run"].get("timed_out")) for item in results),
        "physics_reports": sum(bool(item["summary"]["reports"].get("physics_report.md")) for item in results),
        "execution_reports": sum(bool(item["summary"]["reports"].get("execution_report.md")) for item in results),
        "execution_status_files": sum(
            bool(item["summary"]["reports"].get("execution_status.json")) for item in results
        ),
        "benchmark_passed": passed,
        "benchmark_pass_rate": round(passed / total, 6) if total else 0.0,
    }


def write_report(path: Path, report: dict[str, Any]) -> None:
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases-file", required=True, type=Path)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--case-id", action="append", default=[])
    parser.add_argument("--limit", type=int)
    parser.add_argument("--workflow-timeout", type=float, default=3600.0)
    parser.add_argument("--cleanup-interval", type=int, default=0)
    parser.add_argument("--cleanup-final", action="store_true", default=False)
    parser.add_argument("--no-cleanup-final", action="store_false", dest="cleanup_final")
    parser.add_argument("--run-as-user")
    parser.add_argument("--allow-root-openfoam", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    execution_group = parser.add_mutually_exclusive_group()
    execution_group.add_argument(
        "--enable-execution",
        dest="execution_enabled",
        action="store_true",
        help="启用 solver 执行（默认行为；保留该参数以兼容既有命令）。",
    )
    execution_group.add_argument(
        "--disable-execution",
        dest="execution_enabled",
        action="store_false",
        help="本次 benchmark 禁止所有 solver 和 OpenFOAM 工具执行。",
    )
    parser.set_defaults(execution_enabled=True)
    parser.add_argument("--dsh-bin", type=Path, default=DEFAULT_DSH_BIN)
    parser.add_argument("--dsh-home", type=Path, default=DEFAULT_DSH_HOME)
    parser.add_argument("--dsh-profile", default="headless")
    parser.add_argument("--patch", action="append", type=Path, default=[])
    parser.add_argument("--tutorials-path", type=Path, default=DEFAULT_TUTORIALS)
    parser.add_argument(
        "--api-key-file",
        type=Path,
        default=Path(os.environ["PRINCIPIA_DSH_API_KEY_FILE"])
        if os.environ.get("PRINCIPIA_DSH_API_KEY_FILE")
        else None,
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    benchmark, cases = load_cases(args.cases_file.resolve())
    selected = select_cases(cases, args.case_id, args.limit)

    output_root = args.output_root.resolve()
    run_root = output_root / run_id_now()
    run_root.mkdir(parents=True, exist_ok=False)
    case_root = run_root / "cases"
    logs_root = run_root / "logs"
    execution_enabled = bool(args.execution_enabled)

    if not args.dry_run:
        if not args.dsh_bin.is_file():
            raise FileNotFoundError(f"DSH CLI not found: {args.dsh_bin}")
        if args.api_key_file is not None and not args.api_key_file.is_file():
            raise FileNotFoundError(f"API key file not found: {args.api_key_file}")

    report: dict[str, Any] = {
        "run_id": run_root.name,
        "created_at": utc_now(),
        "benchmark": benchmark,
        "settings": {
            "adapter": "principia-blastfoam-dsh",
            "cases_file": str(args.cases_file.resolve()),
            "dsh_bin": str(args.dsh_bin.resolve()),
            "dsh_home": str(args.dsh_home.resolve()),
            "dsh_profile": args.dsh_profile,
            "patches": [str(path.resolve()) for path in args.patch],
            "tutorials_path": str(args.tutorials_path.resolve()),
            "workflow_timeout": args.workflow_timeout,
            "dry_run": args.dry_run,
            "execution_enabled": execution_enabled,
            "api_key_configured": bool(args.api_key_file or os.environ.get("DEEPSEEK_API_KEY")),
            "cleanup_interval": args.cleanup_interval,
            "cleanup_final": args.cleanup_final,
            "allow_root_openfoam": args.allow_root_openfoam,
        },
        "aggregate": {},
        "results": [],
    }

    for case in selected:
        case_id = str(case["id"])
        case_path = case_root / safe_name(case_id)
        log_path = logs_root / f"{safe_name(case_id)}.log"
        prompt = build_case_prompt(
            case,
            case_path,
            args.tutorials_path.resolve(),
            execution_enabled=execution_enabled,
        )
        command = build_dsh_command(args.dsh_bin.resolve(), args.dsh_profile, prompt, args.patch)

        if args.dry_run:
            run = {
                "exit_code": None,
                "elapsed_seconds": 0.0,
                "timed_out": False,
                "dry_run": True,
                "command": public_command(command),
            }
        else:
            environment = build_child_environment(
                dsh_home=args.dsh_home.resolve(),
                case_root=case_root,
                tutorials_path=args.tutorials_path.resolve(),
                execution_enabled=execution_enabled,
                api_key_file=args.api_key_file.resolve() if args.api_key_file else None,
                run_as_user=args.run_as_user,
            )
            run = run_command(
                command,
                cwd=PROJECT_ROOT,
                environment=environment,
                timeout_seconds=args.workflow_timeout,
                log_path=log_path,
            )

        summary = collect_summary(
            case,
            case_path,
            log_path,
            execution_enabled=execution_enabled,
        )
        item = {
            "case_id": case_id,
            "title": case.get("title", case_id),
            "tags": case.get("tags", []),
            "difficulty": case.get("difficulty"),
            "run": run,
            "summary": summary,
            "benchmark_passed": result_passed(run, summary, execution_enabled),
            "cleanup": {
                "requested": bool(args.cleanup_final),
                "performed": False,
                "reason": "adapter preserves benchmark evidence; campaign harness owns cleanup",
            },
        }
        report["results"].append(item)
        report["aggregate"] = aggregate_results(report["results"])
        write_report(run_root / "benchmark_partial.json", report)

    report["aggregate"] = aggregate_results(report["results"])
    write_report(run_root / "benchmark_report.json", report)
    print(run_root / "benchmark_report.json")

    if args.dry_run:
        return 0
    return 0 if report["aggregate"]["benchmark_passed"] == len(selected) else 1


if __name__ == "__main__":
    raise SystemExit(main())
