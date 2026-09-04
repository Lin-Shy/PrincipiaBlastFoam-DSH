from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from principia_core.utils.execution_status import read_execution_status
from principia_core.utils.workflow_artifacts import artifact_contract_path


PROBE_LOCATIONS_RE = re.compile(r"probeLocations\s*\(\s*(.*?)\s*\)\s*;", flags=re.DOTALL)


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _parse_dict_scalar(text: str, keyword: str) -> str | None:
    match = re.search(rf"^\s*{re.escape(keyword)}\s+([^;]+);", text, flags=re.MULTILINE)
    return match.group(1).strip() if match else None


def _control_dicts(case_dir: Path) -> list[Path]:
    root_control = case_dir / "system" / "controlDict"
    if root_control.exists():
        return [root_control]
    return sorted(
        path
        for path in case_dir.glob("**/system/controlDict")
        if path.is_file() and ".git" not in path.parts
    )


def _relative_path(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _extract_probe_location_blocks(text: str) -> list[list[str]]:
    blocks: list[list[str]] = []
    for match in PROBE_LOCATIONS_RE.finditer(text):
        body = match.group(1)
        locations = [item.strip() for item in re.findall(r"\([^()]+\)", body)]
        if not locations and body.strip():
            locations = [" ".join(body.split())]
        blocks.append(locations)
    return blocks


def collect_control_summaries(case_path: str | Path) -> list[dict[str, Any]]:
    case_dir = Path(case_path)
    summaries: list[dict[str, Any]] = []
    for control in _control_dicts(case_dir):
        text = _read_text(control)
        summaries.append(
            {
                "path": _relative_path(control, case_dir),
                "application": _parse_dict_scalar(text, "application"),
                "endTime": _parse_dict_scalar(text, "endTime"),
                "writeInterval": _parse_dict_scalar(text, "writeInterval"),
                "probeLocations": _extract_probe_location_blocks(text),
            }
        )
    return summaries


def _format_probe_locations(locations: list[str], *, limit: int = 10) -> str:
    if len(locations) <= limit:
        return ", ".join(locations)
    head_count = max(1, limit // 2)
    tail_count = max(1, limit - head_count)
    return ", ".join(locations[:head_count] + ["..."] + locations[-tail_count:])


def format_final_artifact_summary(
    case_path: str | Path,
    *,
    contract: dict[str, Any] | None = None,
    evidence: dict[str, Any] | None = None,
) -> str:
    """Return a concise, file-backed terminal summary for CLI output."""
    case_dir = Path(case_path)
    contract = contract if contract is not None else _read_json(artifact_contract_path(case_dir))
    evidence = evidence if evidence is not None else _read_json(case_dir / "workflow_evidence.json")
    execution_status = read_execution_status(case_dir)
    post_report = case_dir / "post_processing_report.md"
    post_processing = evidence.get("post_processing") if isinstance(evidence, dict) else {}
    post_files = post_processing.get("files") if isinstance(post_processing, dict) else []

    lines = [
        f"case_path: {case_dir}",
        f"artifact_contract ok: {contract.get('ok')}",
    ]

    issues = contract.get("issues") if isinstance(contract, dict) else []
    if issues:
        lines.append("contract issues:")
        for issue in issues[:10]:
            lines.append(f"- {issue}")
        if len(issues) > 10:
            lines.append(f"- ... {len(issues) - 10} more issue(s)")
    else:
        lines.append("contract issues: none")

    if execution_status:
        lines.append(
            "execution_status: "
            f"{execution_status.get('run_status')} / {execution_status.get('final_status')} "
            f"(source={execution_status.get('status_source')})"
        )
        solver_logs = execution_status.get("solver_logs") or []
        if solver_logs:
            lines.append("solver_logs: " + ", ".join(str(item) for item in solver_logs[:8]))
    else:
        lines.append("execution_status: not present")

    controls = collect_control_summaries(case_dir)
    if controls:
        lines.append("controlDict summaries:")
        for control in controls:
            lines.append(
                "- "
                f"{control['path']}: application={control.get('application')}, "
                f"endTime={control.get('endTime')}, "
                f"writeInterval={control.get('writeInterval')}"
            )
            for index, locations in enumerate(control.get("probeLocations") or [], start=1):
                lines.append(f"  probeLocations[{index}]: {_format_probe_locations(locations)}")
    else:
        lines.append("controlDict summaries: none found")

    lines.append(f"post_processing_report.md: exists={post_report.exists()}")
    if post_files:
        listed_files = ", ".join(str(item.get("path")) for item in post_files[:8] if isinstance(item, dict))
        lines.append(f"postProcessing files: {listed_files}")
        if len(post_files) > 8:
            lines.append(f"postProcessing files omitted: {len(post_files) - 8}")
    else:
        exists = (case_dir / "postProcessing").exists()
        lines.append(f"postProcessing directory: exists={exists}")

    return "\n".join(lines).rstrip()
