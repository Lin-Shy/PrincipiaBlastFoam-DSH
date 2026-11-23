"""Independently check the numerical and provenance portions of a sealed PIPE-01 ZIP."""
import argparse
import csv
import hashlib
import io
import json
import math
import zipfile

from run_pair import ARMS, PAIR, read, sha
from pipe_client import validate


def verify(arm):
    root = PAIR/arm
    archive = root/"submission.zip"
    sealed = read(root/"sealed.json")
    if sha(archive) != sealed["archive_sha256"]:
        raise ValueError("sealed ZIP changed")
    receipt = read(root/"operator/verified.json")
    with zipfile.ZipFile(archive) as z:
        def take(name):
            matches = [n for n in z.namelist() if n.split("/")[-1] == name]
            if len(matches) != 1:
                raise ValueError(f"expected exactly one {name}")
            return z.read(matches[0])
        profile = take("profile.csv")
        if hashlib.sha256(profile).hexdigest() != receipt["profile_sha256"]:
            raise ValueError("submitted profile differs from node result")
        case = json.loads(take("case.json").decode("utf-8-sig"))
        validate(case)
        same_matrix = case == read(root/"operator/input/case.json")
        summary = json.loads(take("summary.json").decode("utf-8-sig"))
        if not any(json.loads(z.read(n).decode("utf-8-sig")) == receipt for n in z.namelist()
                   if n.lower().endswith(".json") and "receipt" in n.lower()):
            raise ValueError("matching node receipt missing")
    data = list(csv.DictReader(io.StringIO(profile.decode("ascii"))))
    if len(data) != 65:
        raise ValueError("wrong number of radial nodes")
    radii = [float(d["r_m"]) for d in data]
    velocity = [float(d["u_m_s"]) for d in data]
    if radii != [row[0] for row in case["rows"]] or not all(map(math.isfinite, velocity)):
        raise ValueError("grid or velocity invalid")
    analytic = [0.8/(4*.001)*(.01**2-r**2) for r in radii]
    error = max(abs(a-u) for a,u in zip(analytic,velocity))
    exact_flow = math.pi*.8*.01**4/(8*.001)
    integrated = math.pi*sum((r1-r0)*(r0*u0+r1*u1)
        for r0,r1,u0,u1 in zip(radii,radii[1:],velocity,velocity[1:]))
    flow_error = abs(summary["flow_m3_s"]/exact_flow-1)
    success = error <= .0001 and flow_error <= .01 and abs(summary["center_m_s"]-velocity[0]) <= 1e-8
    return dict(job_id=receipt["job_id"],grid_nodes=len(data),max_velocity_error_m_s=error,
                delivered_matrix_matches_staged=same_matrix,center_m_s=velocity[0],
                submitted_flow_m3_s=summary["flow_m3_s"],independent_trapezoid_flow_m3_s=integrated,
                flow_relative_error=flow_error,exact_flow_m3_s=exact_flow,numerical_checks_passed=success,
                reproduction="independently review README, generation and postprocessing")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("arm",choices=ARMS)
    result = verify(parser.parse_args().arm)
    print(json.dumps(result,indent=2))
    raise SystemExit(0 if result["numerical_checks_passed"] and result["delivered_matrix_matches_staged"] else 1)
