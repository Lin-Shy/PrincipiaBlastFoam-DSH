from __future__ import annotations

import re
from pathlib import Path
from typing import Any


NUMERIC_TIME_DIR_RE = re.compile(r"^\d+(?:\.\d+)?(?:[eE][+-]?\d+)?$")


def _time_key(value: str) -> float:
    try:
        return float(value)
    except ValueError:
        return 0.0


def discover_numeric_time_dirs(case_dir: Path, max_dirs: int = 240) -> list[dict[str, Any]]:
    """Discover root and nested OpenFOAM numeric time directories."""
    if not case_dir.exists():
        return []

    records: list[dict[str, Any]] = []
    for path in sorted(case_dir.rglob("*")):
        if not path.is_dir() or not NUMERIC_TIME_DIR_RE.fullmatch(path.name):
            continue
        records.append(
            {
                "time": path.name,
                "path": str(path.relative_to(case_dir)),
            }
        )
        if len(records) >= max_dirs:
            break
    return sorted(records, key=lambda item: (_time_key(str(item["time"])), str(item["path"])))


def unique_numeric_time_values(records: list[dict[str, Any]]) -> list[str]:
    values = {str(item.get("time")) for item in records if item.get("time") is not None}
    return sorted(values, key=_time_key)
