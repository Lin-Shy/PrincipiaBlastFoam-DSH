"""Read-only OpenFOAM/blastFoam pressure probe time-history extraction and waveform landmark summary."""
from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any


PROBE_HEADER_RE = re.compile(
    r"^#\s*Probe\s+(\d+)\s+\(\s*([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)\s+([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)\s+([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)\s*\)"
)


def _resolve_probe_files(case: Path, probe_dir: str | None) -> list[Path]:
    if probe_dir is not None:
        raw = Path(probe_dir)
        target = (case / raw if not raw.is_absolute() else raw).resolve()
        if target != case and not target.is_relative_to(case):
            raise ValueError("probe_dir must remain strictly within case_path.")
        if target.is_file():
            return [target]
        if not target.is_dir():
            return []
        search_root = target
    else:
        pp = case / "postProcessing"
        if not pp.is_dir():
            return []
        search_root = pp

    candidates = sorted(p for p in search_root.rglob("p") if p.is_file())
    if not candidates and probe_dir is not None:
        candidates = sorted(p for p in search_root.rglob("*") if p.is_file() and p.name in {"p", "p.dat", "pressure"})
    return candidates


def _parse_probe_file(path: Path) -> tuple[dict[int, tuple[float, float, float]], list[float], dict[int, list[float]], bool]:
    coords: dict[int, tuple[float, float, float]] = {}
    times: list[float] = []
    series: dict[int, list[float]] = {}
    has_nonfinite = False

    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            m = PROBE_HEADER_RE.match(stripped)
            if m:
                coords[int(m.group(1))] = (float(m.group(2)), float(m.group(3)), float(m.group(4)))
            continue
        parts = stripped.split()
        if len(parts) < 2:
            continue
        try:
            vals = [float(x) for x in parts]
        except ValueError:
            has_nonfinite = True
            continue
        if any(not math.isfinite(v) for v in vals):
            has_nonfinite = True
            continue
        times.append(vals[0])
        for idx, pval in enumerate(vals[1:]):
            series.setdefault(idx, []).append(pval)
    return coords, times, series, has_nonfinite


def _summarize_series(times: list[float], pressures: list[float], ambient_pa: float, has_nonfinite: bool) -> dict[str, Any]:
    if not times or not pressures or len(times) != len(pressures):
        return {
            "n_samples": 0,
            "has_nonfinite": has_nonfinite,
            "t_min": None,
            "t_max": None,
            "p_max_pa": None,
            "p_over_max_pa": None,
            "t_peak_s": None,
            "t_arrival_s": None,
            "positive_duration_s": None,
            "i_pos_pa_s": 0.0,
            "p_under_min_pa": None,
            "secondary_peaks": [],
        }

    over = [p - ambient_pa for p in pressures]
    peak_idx = max(range(len(over)), key=lambda i: over[i])
    p_over_max = over[peak_idx]
    p_max = pressures[peak_idx]
    t_peak = times[peak_idx]
    p_under_min = min(over)

    arrival_thresh = max(0.01 * p_over_max, 1.0) if p_over_max > 0.0 else float("inf")
    arr_idx = next((i for i, dp in enumerate(over) if dp >= arrival_thresh), None)
    t_arrival = times[arr_idx] if arr_idx is not None else None

    end_pos_time = times[-1]
    if arr_idx is not None and peak_idx >= arr_idx:
        for i in range(max(arr_idx + 1, peak_idx + 1), len(over)):
            if over[i] <= 0.0:
                prev_dp, curr_dp = over[i - 1], over[i]
                denom = prev_dp - curr_dp
                frac = prev_dp / denom if abs(denom) > 1e-18 else 0.0
                end_pos_time = times[i - 1] + frac * (times[i] - times[i - 1])
                break
        pos_duration = max(0.0, end_pos_time - times[arr_idx])
    else:
        pos_duration = 0.0

    # Trapezoidal positive impulse over positive phase [t_arrival, end_pos_time]
    i_pos = 0.0
    if arr_idx is not None and p_over_max > 0.0:
        for i in range(arr_idx, len(over) - 1):
            if times[i] >= end_pos_time:
                break
            t0, t1 = times[i], min(times[i + 1], end_pos_time)
            if t1 <= t0:
                continue
            y0 = max(0.0, over[i])
            if times[i + 1] > end_pos_time and times[i + 1] > times[i]:
                alpha = (end_pos_time - times[i]) / (times[i + 1] - times[i])
                y1 = max(0.0, over[i] + alpha * (over[i + 1] - over[i]))
            else:
                y1 = max(0.0, over[i + 1])
            i_pos += 0.5 * (y0 + y1) * (t1 - t0)

    # Prominent secondary peaks after primary peak (minimum prominence 5% of p_over_max)
    secondary: list[dict[str, float]] = []
    if p_over_max > 0.0 and len(over) >= 5:
        min_since_peak = over[peak_idx]
        min_prom = 0.05 * p_over_max
        for i in range(peak_idx + 1, len(over) - 1):
            min_since_peak = min(min_since_peak, over[i])
            if over[i] > over[i - 1] and over[i] >= over[i + 1] and (over[i] - min_since_peak) >= min_prom:
                secondary.append({"t_s": times[i], "p_over_pa": over[i], "prominence_pa": over[i] - min_since_peak})
                min_since_peak = over[i]

    return {
        "n_samples": len(times),
        "has_nonfinite": has_nonfinite,
        "t_min": times[0],
        "t_max": times[-1],
        "p_max_pa": p_max,
        "p_over_max_pa": p_over_max,
        "t_peak_s": t_peak,
        "t_arrival_s": t_arrival,
        "positive_duration_s": pos_duration,
        "i_pos_pa_s": i_pos,
        "p_under_min_pa": p_under_min,
        "secondary_peaks": secondary,
    }


def _interp_at(times: list[float], values: list[float], query_t: float) -> float:
    if query_t <= times[0]:
        return values[0]
    if query_t >= times[-1]:
        return values[-1]
    for i in range(len(times) - 1):
        if times[i] <= query_t <= times[i + 1]:
            dt = times[i + 1] - times[i]
            if dt <= 1e-18:
                return values[i]
            alpha = (query_t - times[i]) / dt
            return values[i] + alpha * (values[i + 1] - values[i])
    return values[-1]


def _compare_reference(times: list[float], pressures: list[float], ambient_pa: float, summary: dict[str, Any], ref: list[dict[str, float]]) -> dict[str, Any]:
    ref_sorted = sorted(ref, key=lambda item: float(item["t"]))
    ref_t = [float(item["t"]) for item in ref_sorted]
    ref_p = [float(item.get("p_over", item.get("p", 0.0))) for item in ref_sorted]
    if not ref_t or not times:
        return {"valid": False}
    over = [p - ambient_pa for p in pressures]
    sim_at_ref = [_interp_at(times, over, t) for t in ref_t]

    ref_peak_idx = max(range(len(ref_p)), key=lambda i: ref_p[i])
    ref_peak = ref_p[ref_peak_idx]
    sim_peak = summary["p_over_max_pa"] or 0.0
    peak_ratio = (sim_peak / ref_peak) if abs(ref_peak) > 1e-12 else None

    ref_arr = next((t for t, v in zip(ref_t, ref_p) if v >= max(0.01 * max(ref_peak, 0.0), 1.0)), ref_t[0])
    arrival_delta_s = (summary["t_arrival_s"] - ref_arr) if summary["t_arrival_s"] is not None else None

    n = len(ref_p)
    mean_r = sum(ref_p) / n
    mean_s = sum(sim_at_ref) / n
    cov = sum((r - mean_r) * (s - mean_s) for r, s in zip(ref_p, sim_at_ref))
    std_r = math.sqrt(sum((r - mean_r) ** 2 for r in ref_p))
    std_s = math.sqrt(sum((s - mean_s) ** 2 for s in sim_at_ref))
    pearson_r = cov / (std_r * std_s) if std_r > 1e-12 and std_s > 1e-12 else None

    nonzero = [(abs(s - r) / abs(r)) * 100.0 for r, s in zip(ref_p, sim_at_ref) if abs(r) > 1e-9]
    mape_meta = sum(nonzero) / len(nonzero) if nonzero else None
    peak_ape_meta = (abs(sim_peak - ref_peak) / abs(ref_peak) * 100.0) if abs(ref_peak) > 1e-9 else None

    return {
        "valid": True,
        "peak_ratio": peak_ratio,
        "arrival_delta_s": arrival_delta_s,
        "pearson_r": pearson_r,
        "reference_metadata": {"mape_percent": mape_meta, "peak_ape_percent": peak_ape_meta},
    }


def extract_pressure_summary(
    case_path: str | Path,
    ambient_pa: float = 101325.0,
    probe_dir: str | None = None,
    reference_points: list[dict[str, float]] | dict[str, list[dict[str, float]]] | None = None,
) -> dict[str, Any]:
    """Summarize blast/shock probe pressure histories and optional visual-trend reference comparison."""
    case = Path(case_path).resolve()
    files = _resolve_probe_files(case, probe_dir)
    if not files:
        return {"ok": False, "case_path": str(case), "ambient_pa": ambient_pa, "probe_files": [], "probes": [], "error": "No pressure probe files found."}

    probes_out: list[dict[str, Any]] = []
    any_nonfinite = False
    for fp in files:
        coords, times, series, nonfinite = _parse_probe_file(fp)
        any_nonfinite = any_nonfinite or nonfinite
        rel_fp = fp.relative_to(case).as_posix()
        for idx in sorted(series):
            summary = _summarize_series(times, series[idx], ambient_pa, nonfinite)
            probe_key = f"probe_{idx}"
            item: dict[str, Any] = {
                "file": rel_fp,
                "probe_index": idx,
                "probe_id": probe_key,
                "coords": coords.get(idx),
                **summary,
            }
            ref_pts = None
            if isinstance(reference_points, dict):
                ref_pts = reference_points.get(probe_key) or reference_points.get(str(idx))
            elif isinstance(reference_points, list) and idx == 0:
                ref_pts = reference_points
            if ref_pts:
                item["trend_comparison"] = _compare_reference(times, series[idx], ambient_pa, summary, ref_pts)
            probes_out.append(item)

    return {
        "ok": len(probes_out) > 0,
        "case_path": str(case),
        "ambient_pa": ambient_pa,
        "probe_files": [p.relative_to(case).as_posix() for p in files],
        "has_nonfinite": any_nonfinite,
        "probes": probes_out,
    }
