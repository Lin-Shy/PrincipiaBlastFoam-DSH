"""Read-only structural, JWL, charge-resolution, and BC preflight checks for blastFoam/OpenFOAM cases."""
from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any

from principia_core.local_mesh import estimate_cells
from principia_core.utils.solver_logs import _strip_cpp_comments, parse_control_application

BLAST_SOLVERS = {
    "blastFoam",
    "blastEulerFoam",
    "blastXiFoam",
    "blastReactingFoam",
    "blastParcelFoam",
    "blastFSIFoam",
    "rhoCentralFoam",
    "sonicFoam",
    "sonicDyMFoam",
}


def _read_clean(path: Path) -> str:
    return _strip_cpp_comments(path.read_text(encoding="utf-8", errors="ignore"))


def _extract_scalar(clean_text: str, key: str) -> str | None:
    match = re.search(rf"(?m)^\s*{re.escape(key)}\s+([^;\n]+);", clean_text)
    return match.group(1).strip().strip("\"'") if match else None


def _extract_float(clean_text: str, key: str) -> float | None:
    raw = _extract_scalar(clean_text, key)
    if raw is None:
        return None
    token = raw.split()[-1]
    try:
        return float(token)
    except ValueError:
        return None


def _extract_braced_block(text: str, name: str) -> str | None:
    pattern = re.compile(rf"(?m)(?:^|\s){re.escape(name)}\s*\{{")
    match = pattern.search(text)
    if not match:
        return None
    depth = 0
    start = match.end()
    for idx in range(match.end() - 1, len(text)):
        ch = text[idx]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:idx]
    return None


def _extract_paren_block(text: str, name: str) -> str | None:
    pattern = re.compile(rf"(?m)(?:^|\s){re.escape(name)}\s*\(")
    match = pattern.search(text)
    if not match:
        return None
    depth = 0
    start = match.end()
    for idx in range(match.end() - 1, len(text)):
        ch = text[idx]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                return text[start:idx]
    return None


def _parse_vec3(raw: str) -> tuple[float, float, float] | None:
    nums = re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", raw)
    if len(nums) < 3:
        return None
    return (float(nums[0]), float(nums[1]), float(nums[2]))


def _point_in_box(pt: tuple[float, float, float], bmin: tuple[float, float, float], bmax: tuple[float, float, float]) -> bool:
    return all(bmin[i] - 1e-12 <= pt[i] <= bmax[i] + 1e-12 for i in range(3))


def _dist_point_segment(pt: tuple[float, float, float], a: tuple[float, float, float], b: tuple[float, float, float]) -> float:
    ab = tuple(b[i] - a[i] for i in range(3))
    ap = tuple(pt[i] - a[i] for i in range(3))
    denom = sum(v * v for v in ab)
    t = 0.0 if denom <= 1e-24 else max(0.0, min(1.0, sum(ap[i] * ab[i] for i in range(3)) / denom))
    closest = tuple(a[i] + t * ab[i] for i in range(3))
    return math.sqrt(sum((pt[i] - closest[i]) ** 2 for i in range(3)))


def _mesh_bounds_and_dx(block_text: str) -> dict[str, Any]:
    verts_raw = _extract_paren_block(block_text, "vertices")
    pts: list[tuple[float, float, float]] = []
    if verts_raw:
        scale = _extract_float(block_text, "scale") or _extract_float(block_text, "convertToMeters") or 1.0
        for m in re.finditer(r"\(\s*([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)\s+([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)\s+([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)\s*\)", verts_raw):
            pts.append((float(m.group(1)) * scale, float(m.group(2)) * scale, float(m.group(3)) * scale))
    hex_counts = [
        (int(m.group(1)), int(m.group(2)), int(m.group(3)))
        for m in re.finditer(r"\bhex\s*\([^)]+\)\s*\(\s*(\d+)\s+(\d+)\s+(\d+)\s*\)", block_text)
    ]
    info: dict[str, Any] = {"estimated_cells": None, "bounds": None, "approx_max_dx": None}
    try:
        info["estimated_cells"] = estimate_cells(block_text)
    except ValueError:
        info["estimated_cells"] = None
    if pts:
        bmin = tuple(min(p[i] for p in pts) for i in range(3))
        bmax = tuple(max(p[i] for p in pts) for i in range(3))
        info["bounds"] = {"min": bmin, "max": bmax}
        if len(hex_counts) == 1:
            nx, ny, nz = hex_counts[0]
            spans = [bmax[i] - bmin[i] for i in range(3)]
            dxs = [spans[i] / max(1, (nx, ny, nz)[i]) for i in range(3) if spans[i] > 0]
            if dxs:
                info["approx_max_dx"] = max(dxs)
    return info


def _mesh_patch_names(case: Path) -> set[str]:
    poly_boundary = case / "constant" / "polyMesh" / "boundary"
    if poly_boundary.is_file():
        clean = _read_clean(poly_boundary)
        names = set(re.findall(r"(?m)^\s*([A-Za-z_][\w.-]*)\s*\{[^}]*\btype\b", clean, re.DOTALL))
        if names:
            return names
    block_dict = case / "system" / "blockMeshDict"
    if block_dict.is_file():
        clean = _read_clean(block_dict)
        b_block = _extract_paren_block(clean, "boundary")
        if b_block:
            return set(re.findall(r"(?m)^\s*([A-Za-z_][\w.-]*)\s*\{", b_block))
    return set()


def _field_dir(case: Path) -> Path | None:
    for rel in ("0", "0.orig"):
        d = case / rel
        if d.is_dir():
            return d
    return None


def preflight_blast_case(case_path: str | Path) -> dict[str, Any]:
    """Run read-only structural, JWL, charge-resolution, decomposition, and BC consistency checks."""
    case = Path(case_path).resolve()
    errors: list[str] = []
    warnings: list[str] = []
    checks: dict[str, Any] = {}

    # 1. Required directories and dictionaries
    required_files = [
        ("system/controlDict", case / "system" / "controlDict"),
        ("system/fvSchemes", case / "system" / "fvSchemes"),
        ("system/fvSolution", case / "system" / "fvSolution"),
    ]
    missing_req = [name for name, path in required_files if not path.is_file()]
    field_dir = _field_dir(case)
    if field_dir is None:
        missing_req.append("0/ or 0.orig/")
    for item in missing_req:
        errors.append(f"Missing required case artifact: {item}")

    solver = parse_control_application(case)
    is_blast = bool(solver and (solver in BLAST_SOLVERS or solver.startswith("blast")))

    has_phase = (case / "constant" / "phaseProperties").is_file()
    has_thermo = (case / "constant" / "thermophysicalProperties").is_file()
    if is_blast and solver.startswith("blast") and not has_phase and not has_thermo:
        errors.append("blastFoam solver requires constant/phaseProperties or constant/thermophysicalProperties.")
    elif not has_phase and not has_thermo:
        warnings.append("Neither constant/phaseProperties nor constant/thermophysicalProperties found.")
    checks["structure"] = {
        "missing": missing_req,
        "field_dir": field_dir.name if field_dir else None,
        "has_phaseProperties": has_phase,
        "has_thermophysicalProperties": has_thermo,
    }

    # 2. controlDict checks
    ctrl_info: dict[str, Any] = {"application": solver}
    ctrl_path = case / "system" / "controlDict"
    if ctrl_path.is_file():
        ctrl_txt = _read_clean(ctrl_path)
        t0 = _extract_float(ctrl_txt, "startTime")
        t1 = _extract_float(ctrl_txt, "endTime")
        dt = _extract_float(ctrl_txt, "deltaT")
        max_co = _extract_float(ctrl_txt, "maxCo")
        adjust = _extract_scalar(ctrl_txt, "adjustTimeStep")
        has_probes = bool(re.search(r"\bprobes\b|\btype\s+probes\s*;", ctrl_txt))
        ctrl_info.update(startTime=t0, endTime=t1, deltaT=dt, maxCo=max_co, adjustTimeStep=adjust, has_probes=has_probes)
        if t0 is not None and t1 is not None and t1 <= t0:
            errors.append(f"controlDict endTime ({t1}) must exceed startTime ({t0}).")
        if dt is not None and dt <= 0:
            errors.append(f"controlDict deltaT ({dt}) must be positive.")
        if max_co is not None and max_co <= 0:
            errors.append(f"controlDict maxCo ({max_co}) must be positive.")
        if is_blast:
            if max_co is None:
                warnings.append("Blast solver controlDict omits maxCo; compressible stability requires explicit CFL control.")
            elif max_co > 0.5:
                warnings.append(f"Blast solver controlDict maxCo={max_co} > 0.5; risk of shock instability or divergence.")
            if (adjust or "").lower() not in {"yes", "true", "on"}:
                warnings.append("Blast solver controlDict adjustTimeStep is not enabled (yes/true).")
            if not has_probes:
                warnings.append("controlDict defines no probes functionObject for pressure-time extraction.")
    checks["controlDict"] = ctrl_info

    # 3. phaseProperties JWL + charge initialization + mesh resolution
    charge_info: dict[str, Any] = {}
    phase_path = case / "constant" / "phaseProperties"
    det_points: list[tuple[float, float, float]] = []
    if phase_path.is_file():
        phase_txt = _read_clean(phase_path)
        eos = _extract_scalar(phase_txt, "equationOfState") or ("JWL" if "JWL" in phase_txt else None)
        act = _extract_scalar(phase_txt, "activationModel")
        jwl_vals = {k: _extract_float(phase_txt, k) for k in ("rho0", "e0", "A", "B", "R1", "R2", "omega")}
        det_block = _extract_paren_block(phase_txt, "detonationPoints") or ""
        for m in re.finditer(r"\(\s*([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)\s+([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)\s+([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)\s*\)", det_block):
            det_points.append((float(m.group(1)), float(m.group(2)), float(m.group(3))))
        charge_info.update(equationOfState=eos, activationModel=act, jwl=jwl_vals, detonationPoints=det_points)
        if eos and "jwl" in eos.lower():
            missing_jwl = [k for k, v in jwl_vals.items() if v is None]
            if missing_jwl:
                errors.append(f"JWL EOS missing required parameters in phaseProperties: {', '.join(missing_jwl)}.")
            for pos_key in ("rho0", "R1", "R2"):
                if jwl_vals[pos_key] is not None and jwl_vals[pos_key] <= 0:
                    errors.append(f"JWL parameter {pos_key}={jwl_vals[pos_key]} must be positive.")

    mesh_info = _mesh_bounds_and_dx(_read_clean(case / "system" / "blockMeshDict")) if (case / "system" / "blockMeshDict").is_file() else {}
    charge_geom: dict[str, Any] = {}
    for dict_name in ("setFieldsDict", "setRefinedFieldsDict"):
        dp = case / "system" / dict_name
        if not dp.is_file():
            continue
        dtxt = _read_clean(dp)
        sph = _extract_braced_block(dtxt, "sphereToCell")
        cyl = _extract_braced_block(dtxt, "cylinderToCell")
        box_m = re.search(r"\bbox\s*\(([^)]+)\)\s*\(([^)]+)\)", dtxt)
        if sph:
            c_raw = re.search(r"\bcentre\s*\(([^)]+)\)", sph)
            r = _extract_float(sph, "radius")
            centre = _parse_vec3(c_raw.group(1)) if c_raw else None
            charge_geom = {"shape": "sphereToCell", "centre": centre, "radius": r, "dict": dict_name}
            if r is not None and r <= 0:
                errors.append(f"{dict_name} sphereToCell radius ({r}) must be positive.")
            if centre and r and det_points:
                for pt in det_points:
                    if math.sqrt(sum((pt[i] - centre[i]) ** 2 for i in range(3))) > r + 1e-12:
                        errors.append(f"Detonation point {pt} lies outside sphereToCell charge (centre={centre}, radius={r}).")
            if r and mesh_info.get("approx_max_dx"):
                cells_per_r = r / mesh_info["approx_max_dx"]
                charge_geom["cells_per_radius"] = round(cells_per_r, 3)
                if cells_per_r < 5.0:
                    warnings.append(f"Charge radius resolved by ~{cells_per_r:.2f} cells (< 5 cells/R); shock peak may under-resolve.")
        elif cyl:
            p1_m = re.search(r"\bpoint1\s*\(([^)]+)\)", cyl)
            p2_m = re.search(r"\bpoint2\s*\(([^)]+)\)", cyl)
            r = _extract_float(cyl, "radius")
            p1 = _parse_vec3(p1_m.group(1)) if p1_m else None
            p2 = _parse_vec3(p2_m.group(1)) if p2_m else None
            charge_geom = {"shape": "cylinderToCell", "point1": p1, "point2": p2, "radius": r, "dict": dict_name}
            if r is not None and r <= 0:
                errors.append(f"{dict_name} cylinderToCell radius ({r}) must be positive.")
            if p1 and p2 and r and det_points:
                for pt in det_points:
                    if _dist_point_segment(pt, p1, p2) > r + 1e-12:
                        errors.append(f"Detonation point {pt} lies outside cylinderToCell charge.")
        elif box_m:
            bmin = _parse_vec3(box_m.group(1))
            bmax = _parse_vec3(box_m.group(2))
            charge_geom = {"shape": "boxToCell", "min": bmin, "max": bmax, "dict": dict_name}
            if bmin and bmax and det_points:
                for pt in det_points:
                    if not _point_in_box(pt, bmin, bmax):
                        errors.append(f"Detonation point {pt} lies outside boxToCell charge bounds {bmin}..{bmax}.")
        break
    if det_points and mesh_info.get("bounds"):
        bmin = mesh_info["bounds"]["min"]
        bmax = mesh_info["bounds"]["max"]
        for pt in det_points:
            if not _point_in_box(pt, bmin, bmax):
                errors.append(f"Detonation point {pt} lies outside blockMeshDict domain bounds {bmin}..{bmax}.")
    charge_info["mesh"] = mesh_info
    charge_info["charge_geometry"] = charge_geom
    checks["charge_and_mesh"] = charge_info

    # 4. decomposeParDict consistency
    decomp_info: dict[str, Any] = {}
    decomp_path = case / "system" / "decomposeParDict"
    if decomp_path.is_file():
        dtxt = _read_clean(decomp_path)
        nsub = _extract_float(dtxt, "numberOfSubdomains")
        method = _extract_scalar(dtxt, "method")
        decomp_info.update(numberOfSubdomains=int(nsub) if nsub is not None else None, method=method)
        for coeff_name in ("simpleCoeffs", "hierarchicalCoeffs"):
            blk = _extract_braced_block(dtxt, coeff_name)
            if blk:
                n_m = re.search(r"\bn\s*\(\s*(\d+)\s+(\d+)\s+(\d+)\s*\)", blk)
                if n_m and method and method.lower() in coeff_name.lower():
                    prod = int(n_m.group(1)) * int(n_m.group(2)) * int(n_m.group(3))
                    decomp_info["coeffs_product"] = prod
                    if nsub is not None and int(nsub) != prod:
                        errors.append(f"decomposeParDict numberOfSubdomains ({int(nsub)}) != {coeff_name} product ({prod}).")
    checks["decomposeParDict"] = decomp_info

    # 5. Boundary patch consistency
    patch_info: dict[str, Any] = {}
    mesh_patches = _mesh_patch_names(case)
    if mesh_patches and field_dir is not None:
        field_checks: dict[str, list[str]] = {}
        for fname in ("p", "U", "T"):
            fp = field_dir / fname
            if not fp.is_file():
                continue
            ftxt = _read_clean(fp)
            bf = _extract_braced_block(ftxt, "boundaryField")
            if bf is None:
                errors.append(f"{field_dir.name}/{fname} is missing boundaryField.")
                continue
            defined = set(re.findall(r"(?m)^\s*([A-Za-z_][\w.-]*)\s*\{", bf))
            has_wildcard = bool(re.search(r'"[^"]*\*[^"]*"', bf))
            missing_patches = sorted(mesh_patches - defined) if not has_wildcard else []
            if missing_patches:
                field_checks[fname] = missing_patches
                errors.append(f"{field_dir.name}/{fname} missing mesh boundary patches: {', '.join(missing_patches)}.")
        patch_info = {"mesh_patches": sorted(mesh_patches), "missing_by_field": field_checks}
    checks["patches"] = patch_info

    return {
        "ok": len(errors) == 0,
        "case_path": str(case),
        "solver": solver,
        "checks": checks,
        "errors": errors,
        "warnings": warnings,
        "summary": {
            "error_count": len(errors),
            "warning_count": len(warnings),
            "estimated_cells": mesh_info.get("estimated_cells"),
        },
    }
