"""Research-side consistency ablation, not a scientific-success evaluator.

The independent binding is a trust assumption. A source hash alone cannot prove
pressure semantics, physical validity, or who produced a file. No hidden reference
values are loaded here. Only whole-window peak overpressure is implemented.
"""
import hashlib
import math
from pathlib import Path

try:
    from .pressure_observations import read_scalar_probes, window, metrics
except ImportError:
    from pressure_observations import read_scalar_probes, window, metrics


def audit_claim(source: Path, request: dict, claim: dict, binding: dict | None, *, level="bound"):
    if level not in {"numeric", "declared", "bound"}:
        raise ValueError("Unknown audit level")
    def result(status, reason, **extra):
        return {"status": status, "reason": reason, "level": level, "task_success": None, **extra}
    value = claim.get("value")
    if isinstance(value, bool) or not isinstance(value, (float, int)) or not math.isfinite(value):
        return result("reject", "nonfinite_or_missing_value")
    if level == "numeric":
        return result("consistent", "finite_number_only")
    for key in ("observable", "gauge", "window_s", "time_origin"):
        if claim.get(key) != request.get(key):
            return result("reject", "request_mismatch:"+key)
    scales = {"Pa": 1., "kPa": 1000.}
    if claim.get("unit") not in scales:
        return result("reject", "unsupported_pressure_unit")
    if level == "declared":
        return result("consistent", "declarations_only_not_verified")
    if binding is None:
        return result("unknown", "independent_binding_missing")
    sha = hashlib.sha256(source.read_bytes()).hexdigest()
    if sha != binding.get("sha256") or claim.get("source_sha256") != sha:
        return result("reject", "source_hash_mismatch")
    if binding.get("pressure_kind") not in {"absolute", "overpressure"} or binding.get("unit") not in scales:
        return result("unknown", "source_pressure_semantics_unresolved")
    if binding.get("time_unit") != "s" or binding.get("time_origin") != request.get("time_origin"):
        return result("unknown", "source_time_semantics_unresolved")
    if request.get("observable") != "whole_window_peak_overpressure":
        return result("unknown", "observable_not_implemented_no_implicit_substitution")
    gauge = binding.get("gauges", {}).get(request["gauge"])
    if gauge is None:
        return result("unknown", "gauge_binding_missing")
    if gauge.get("actual_position_m") is None or request.get("position_tolerance_m") is None:
        return result("unknown", "sampling_position_or_tolerance_missing")
    actual, target = gauge["actual_position_m"], request.get("target_position_m", [])
    if len(actual) != 3 or len(target) != 3:
        return result("unknown", "invalid_position_metadata")
    numbers = [*actual, *target, request["position_tolerance_m"]]
    if any(isinstance(x, bool) or not isinstance(x, (float, int)) or not math.isfinite(x) for x in numbers) or request["position_tolerance_m"] < 0:
        return result("unknown", "invalid_position_metadata")
    distance = math.dist(actual, target)
    if distance > request["position_tolerance_m"]:
        return result("reject", "sampling_position_outside_task_tolerance", distance_m=distance)
    if binding["pressure_kind"] == "absolute" and binding.get("ambient_pa") is None:
        return result("unknown", "ambient_pressure_missing")
    if binding["pressure_kind"] == "absolute" and (isinstance(binding["ambient_pa"], bool) or not isinstance(binding["ambient_pa"], (float, int)) or not math.isfinite(binding["ambient_pa"])):
        return result("unknown", "ambient_pressure_invalid")
    try:
        rows = read_scalar_probes(source)
        column = gauge["column"]
        if not isinstance(column, int) or column < 0 or column >= len(rows[0])-1:
            return result("unknown", "invalid_column_binding")
        factor = scales[binding["unit"]]
        normalized = [(row[0], row[column+1]*factor) for row in rows]
        selected = window(normalized, *request["window_s"])
        computed = metrics(selected, ambient_pa=binding.get("ambient_pa", 0.) if binding["pressure_kind"] == "absolute" else 0., pressure_unit="Pa")[0]["peak_overpressure_pa"]
    except ValueError as exc:
        return result("reject", "raw_data_invalid:"+str(exc))
    supplied = value*scales[claim["unit"]]
    # Arithmetic reproducibility only; this is NOT a physical accuracy threshold.
    if not math.isclose(supplied, computed, rel_tol=1e-9, abs_tol=1e-6):
        return result("reject", "claim_not_reproduced_from_bound_source", computed_pa=computed)
    return result("consistent", "bound_claim_reproduced_not_physical_success", computed_pa=computed)
