from __future__ import annotations

from pathlib import Path
from typing import Any

from principia_core.utils.postprocessing_contracts import discover_probe_fields
from principia_core.utils.time_dirs import discover_numeric_time_dirs, unique_numeric_time_values


def _numeric_time_dirs(case_dir: Path) -> list[str]:
    return unique_numeric_time_values(discover_numeric_time_dirs(case_dir))


def _postprocessing_files(case_dir: Path, max_files: int = 80) -> list[dict[str, Any]]:
    root = case_dir / "postProcessing"
    if not root.exists():
        return []

    files: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        files.append({"path": str(path.relative_to(case_dir)), "bytes": path.stat().st_size})
        if len(files) >= max_files:
            break
    return files


def build_post_processing_report(case_path: str | Path) -> tuple[str, dict[str, Any]]:
    case_dir = Path(case_path)
    time_dir_locations = discover_numeric_time_dirs(case_dir)
    time_dirs = unique_numeric_time_values(time_dir_locations)
    files = _postprocessing_files(case_dir)
    probe_fields = {
        "probes": discover_probe_fields(case_dir, "probes"),
        "pressureProbes": discover_probe_fields(case_dir, "pressureProbes"),
    }
    detected_probe_fields = {
        name: fields
        for name, fields in probe_fields.items()
        if fields
    }

    summary = {
        "case_path": str(case_dir),
        "post_processing_exists": (case_dir / "postProcessing").exists(),
        "post_processing_file_count": len(files),
        "time_dir_count": len(time_dirs),
        "last_time": time_dirs[-1] if time_dirs else None,
        "time_dir_locations": time_dir_locations[:40],
        "probe_fields": probe_fields,
        "detected_probe_fields": detected_probe_fields,
        "files": files,
    }
    probe_fields_text = (
        "; ".join(f"{name}: {', '.join(fields)}" for name, fields in detected_probe_fields.items())
        if detected_probe_fields
        else "none detected"
    )

    lines = [
        "# Post-Processing Report",
        "",
        "## Output Summary",
        f"- Time directories: `{len(time_dirs)}`",
        f"- Last available time: `{time_dirs[-1] if time_dirs else 'unavailable'}`",
        f"- Time directory locations listed: `{min(len(time_dir_locations), 40)}`",
        f"- postProcessing directory: `{summary['post_processing_exists']}`",
        f"- postProcessing files listed: `{len(files)}`",
        f"- probe fields: `{probe_fields_text}`",
        "",
        "## Available Files",
    ]
    if files:
        for item in files[:40]:
            lines.append(f"- `{item['path']}` ({item['bytes']} bytes)")
        if len(files) > 40:
            lines.append(f"- ... {len(files) - 40} additional files omitted from this compact report")
    else:
        lines.append("- No postProcessing files were found. Use solver logs and time directories as the available evidence.")

    if time_dir_locations:
        lines.extend(["", "## Time Directory Locations"])
        for item in time_dir_locations[:20]:
            lines.append(f"- `{item['path']}`")
        if len(time_dir_locations) > 20:
            lines.append(f"- ... {len(time_dir_locations) - 20} additional time directories omitted from this compact report")

    lines.extend(
        [
            "",
            "## Interpretation",
            "This deterministic report lists available result artifacts only. Quantitative comparison, plotting, or impulse integration should use the listed probe/function-object files and the OpenFOAM dictionaries that generated them.",
        ]
    )
    return "\n".join(lines).rstrip() + "\n", summary


def write_post_processing_report(case_path: str | Path) -> dict[str, Any]:
    report, summary = build_post_processing_report(case_path)
    path = Path(case_path) / "post_processing_report.md"
    path.write_text(report, encoding="utf-8")
    summary["path"] = str(path)
    summary["written"] = True
    return summary
