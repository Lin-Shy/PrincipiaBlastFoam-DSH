"""External condition/completion/delivery checks; never compares a Gold curve."""
from pathlib import Path
import argparse
import json
import math
import re
import sys

PROJECT = Path(__file__).resolve().parents[2]
BENCHMARK = PROJECT.parent / "graduation-datasets/chapter03_simulation_tasks/benchmark"
sys.path.insert(0, str(BENCHMARK))
from evaluator.case_validator import assertions_valid, tokens
from evaluator.foam_fields import read_field
from evaluator.foam_mesh import read_mesh, centre_signature
from evaluator.output_validator import read_probe
from evaluator.physical_validator import validate_initial_phase_mass
from evaluator.numerical_metrics import positive_impulse


def development_assertions(contract):
    extra = []
    for entry, value in {"startTime": "0", "deltaT": "1e-8", "maxCo": "0.5", "maxDeltaT": "1e-6", "adjustTimeStep": "yes", "writeInterval": "0.0001"}.items():
        extra.append({"file": "system/controlDict", "entry": entry, "equals": value})
    for field in ["p", "T", "U", "rho.air", "rho.c4"]:
        extra.append({"file": "0/" + field, "entry": "boundaryField/outlet/type", "equals": "pressureWaveTransmissive" if field == "p" else "zeroGradient"})
    extra.append({"file": "0/alpha.c4", "entry": "boundaryField/outlet/type", "equals": "zeroGradient"})
    # Actual polyMesh geometry is authoritative; scale vs convertToMeters is syntax.
    return contract["configuration_assertions"] + extra


def evaluate(run):
    result = {"sample_id": "C3-DEV-FF-001", "accuracy_scoring": "not_performed",
              "reference_curve_loaded": False, "conditions": "unknown", "completion": "unknown",
              "delivery": "unknown", "model_health": "unknown", "errors": [], "missing_deliverables": []}
    submission = run / "remote_result/submission"
    case = submission / "case"
    if not case.is_dir():
        result.update({"status": "blocked_before_case_delivery", "errors": ["missing_submission_case"]})
        return result
    contract = json.loads((BENCHMARK / "references/contracts/B01-2.yaml").read_text(encoding="utf-8"))
    evidence_path = run / "operator_dictionary_entries.json"
    entries = json.loads(evidence_path.read_text(encoding="utf-8")) if evidence_path.exists() else {}
    boolean = entries.get("system/controlDict:adjustTimeStep")
    if boolean and boolean.get("stdout", "").strip().lower() in {"true", "on", "yes"}:
        entries = {**entries, "system/controlDict:adjustTimeStep": {**boolean, "stdout": "yes"}}
    condition_errors = assertions_valid(development_assertions(contract), entries)
    for field, value, dims in [("p", 101298., [1,-1,-2,0,0,0,0]), ("T", 300., [0,0,0,1,0,0,0]),
                               ("U", 0., [0,1,-1,0,0,0,0]), ("rho.air", 1.225, [1,-3,0,0,0,0,0]),
                               ("rho.c4", 1601., [1,-3,0,0,0,0,0])]:
        try:
            data = read_field(case / "0" / field, contract["binary_layout"])
            if data["dimensions"] != dims or any(abs(x-value) > 64*sys.float_info.epsilon*max(1,abs(value)) for x in data["internal"]):
                condition_errors.append("initial_field_mismatch:" + field)
        except (ValueError, OSError) as e:
            condition_errors.append("initial_field:" + field + ":" + str(e))
    source = BENCHMARK / "development_samples/b01_2_e2e_20261102/public/materials"
    for target, supplied in [("constant/phaseProperties", "phaseProperties"), ("constant/dynamicMeshDict", "dynamicMeshDict"),
                             ("system/fvSchemes", "fvSchemes"), ("system/fvSolution", "fvSolution")]:
        if not (case / target).is_file() or tokens((case / target).read_text(encoding="utf-8")) != tokens((source / supplied).read_text(encoding="utf-8")):
            condition_errors.append("fixed_model_or_numerics_changed:" + target)
    try:
        mesh = read_mesh(case / "constant/polyMesh", contract["binary_layout"])
        if mesh["cell_count"] != 64000 or centre_signature(mesh["cell_centres_m"]) != contract["mesh_geometry"]["centre_signature_sha256"]:
            condition_errors.append("actual_mesh_geometry_mismatch")
        boundary = (case / "constant/polyMesh/boundary").read_text(encoding="utf-8")
        patches = re.findall(r"(\w+)\s*\{([^{}]*)\}", boundary)
        nonempty = [(name, body) for name, body in patches if re.search(r"\bnFaces\s+([1-9][0-9]*)\s*;", body)]
        if len(nonempty) != 1 or nonempty[0][0] != "outlet" or not re.search(r"\btype\s+patch\s*;", nonempty[0][1]):
            condition_errors.append("external_boundary_patches_mismatch")
        condition_errors += validate_initial_phase_mass(case, contract["initial_phase_mass_constraints"], contract["binary_layout"])
    except (ValueError, OSError, KeyError) as e:
        condition_errors.append("mesh_or_initial_source:" + str(e))
    result["case_conditions"] = "pass" if not condition_errors else "fail"
    guard_path = run / "remote_result/execution_jobs/production_01/status.json"
    guard = json.loads(guard_path.read_text(encoding="utf-8")) if guard_path.exists() else None
    resource_known = False
    if guard:
        resource_known = True
        limits = guard.get("proc_limits", "")
        memory = re.search(r"^Max address space\s+(\d+)\s+(\d+)\s+bytes", limits, re.M)
        file_size = re.search(r"^Max file size\s+(\d+)\s+(\d+)\s+bytes", limits, re.M)
        command = guard.get("command", [])
        result["resource_limits"] = {"evidence": str(guard_path.relative_to(run)),
                                     "kind": guard.get("memory_limit_kind"), "guard_status": guard.get("status")}
        if (not command or Path(command[0]).name != "blastFoam" or "-case" not in command):
            condition_errors.append("guard_command_not_serial_blastFoam")
        if not memory or tuple(map(int, memory.groups())) != (3*1024**3, 3*1024**3):
            condition_errors.append("guard_memory_limit_missing_or_mismatched")
        if not file_size or tuple(map(int, file_size.groups())) != (512*1024**2, 512*1024**2):
            condition_errors.append("guard_file_limit_missing_or_mismatched")
        if len(guard.get("cpu_affinity", [])) != 1:
            condition_errors.append("guard_single_cpu_not_observed")
    # Operator observations take precedence over a runner's declared quota.
    resource_receipt = run / "operator_model_stop.json"
    if resource_receipt.exists():
        resource_known = True
        resource = json.loads(resource_receipt.read_text(encoding="utf-8"))
        result["resource_limits"] = {"evidence": resource_receipt.name,
                                     "memory_cap_3GiB_enforced": resource.get("memory_cap_3GiB_enforced")}
        if resource.get("memory_cap_3GiB_enforced") is False:
            condition_errors.append("resource_memory_cap_not_enforced")
    result["conditions"] = "fail" if condition_errors else "pass" if resource_known else "unknown_resources"
    result["errors"] += condition_errors
    series = []
    try:
        for probe in contract["probes"]:
            # Function names are an implementation detail; identify actual sensor headers.
            s = None
            candidates = list((case / "postProcessing").rglob("p")) if (case / "postProcessing").exists() else []
            for path in candidates:
                try:
                    s = read_probe(case, {**probe, "path": path.relative_to(case).as_posix()}, contract)
                    if s["time_s"][0] == 0 and s["time_s"][-1] >= .0005:
                        break
                except (ValueError, OSError):
                    s = None
            if s is None:
                raise ValueError("missing_or_invalid_native_probe:" + probe["sensor_id"])
            t, p = s["time_s"], s["overpressure_pa"]
            if t[0] != 0 or t[-1] < .0005:
                raise ValueError("incomplete_probe_window")
            series.append({"sensor_id": probe["sensor_id"], "samples": len(t),
                           "window_s": [t[0], t[-1]], "peak_overpressure_pa": max(p),
                           "time_of_peak_s": t[p.index(max(p))],
                           "positive_impulse_pa_s": positive_impulse(t, p, 0, .0005)})
        result["native_postprocessing"] = series
    except (ValueError, OSError, KeyError) as e:
        result["errors"].append("native_pressure:" + str(e))
    logs = [p for p in submission.rglob('*') if p.is_file() and 'blastfoam' in p.name.lower() and ('log' in p.name.lower())]
    guard_log = run / "remote_result/execution_jobs/production_01/process.log"
    if guard_log.is_file():
        logs.append(guard_log)
    solver_logs = []
    for p in logs:
        text = p.read_text(encoding="utf-8", errors="replace")
        times = [float(t) for t in re.findall(r"^Time = ([0-9.eE+-]+)\s*$", text, re.M)]
        if times:
            solver_logs.append({"path": str(p.relative_to(run / 'remote_result')), "last_time_s": times[-1],
                                "end": bool(re.search(r"^End\s*$", text, re.M)),
                                "invalid": bool(re.search(r"FOAM FATAL|segmentation fault|\b(?:nan|[+-]?inf)\b", text, re.I)),
                                "nonpositive_T": any(float(v) <= 0 for v in re.findall(r"min\(T\):\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)", text))})
    result["solver_logs"] = solver_logs
    complete = any(x["end"] and x["last_time_s"] >= .0005 and not x["invalid"] for x in solver_logs) and len(series) == 3
    if guard and guard.get("status") != "process_completed":
        complete = False
    final_folders = []
    for path in case.iterdir():
        try:
            if path.is_dir() and math.isfinite(float(path.name)) and float(path.name) >= .0005:
                final_folders.append(path)
        except ValueError:
            pass
    complete = complete and bool(final_folders) and all((max(final_folders, key=lambda p: float(p.name)) / name).is_file() for name in contract["required_fields"])
    result["completion"] = "pass_file_evidence" if complete else "fail_or_incomplete"
    health_errors = []
    observed_fields = 0
    for folder in case.iterdir():
        try:
            numeric = math.isfinite(float(folder.name))
        except ValueError:
            numeric = False
        if not folder.is_dir() or not numeric:
            continue
        for field in ["p", "rho", "T", "alpha.c4", "lambda.c4"]:
            path = folder / field
            if not path.is_file():
                continue
            try:
                values = read_field(path, contract["binary_layout"])["internal"]
                observed_fields += 1
                if field in {"p", "rho", "T"} and min(values) <= 0:
                    health_errors.append(folder.name + "/" + field + ":nonpositive")
                if field in {"alpha.c4", "lambda.c4"} and (min(values) < 0 or max(values) > 1):
                    health_errors.append(folder.name + "/" + field + ":out_of_bounds")
            except (ValueError, OSError) as e:
                health_errors.append(str(path.relative_to(case)) + ":" + str(e))
    if any(x["nonpositive_T"] or x["invalid"] for x in solver_logs):
        health_errors.append("solver_log_model_or_numeric_anomaly")
    if guard and guard.get("status") == "model_anomaly_stop":
        health_errors.append("guard_observed_model_anomaly")
    result["model_health"] = ("observed_anomaly" if health_errors else
                              "unknown_no_solver_evidence" if not observed_fields and not solver_logs else
                              "no_anomaly_in_available_evidence")
    result["errors"] += health_errors
    required = ["run.sh", "pressure.csv", "metrics.json", "figures/pressure.png", "execution.json"]
    missing = [p for p in required if not (submission / p).is_file()]
    if not any((submission / n).is_file() for n in ["report.md", "report.pdf"]):
        missing.append("report.md_or_pdf")
    if not (submission / "logs").is_dir():
        missing.append("logs/")
    result["missing_deliverables"] = missing
    result["delivery"] = "files_present_content_review_required" if not missing else "incomplete"
    result["status"] = ("model_anomaly_stop" if health_errors else
                        "development_incomplete" if not complete or result["conditions"] != "pass" or missing else
                        "development_evidence_collected")
    result["scientific_accuracy_status"] = "not_assessed"
    result["independent_process_receipts"] = "DSH native tool/session records; submission execution.json alone is not operator proof"
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("run_dir", type=Path)
    args = p.parse_args()
    result = evaluate(args.run_dir.resolve())
    (args.run_dir / "development_checks.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ["status", "conditions", "completion", "delivery", "accuracy_scoring"]}, ensure_ascii=False))
