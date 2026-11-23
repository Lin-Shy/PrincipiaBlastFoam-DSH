"""Independent sealed-ZIP data checks for the wall-driven modification task."""
import argparse
import csv
import hashlib
import io
import json
import math
from pathlib import PurePosixPath
import zipfile

from pair import ARMS, PAIR, read, sha


def verify(arm,continuation=False):
    root = PAIR/arm
    segment = root/"continuation" if continuation else root
    archive = segment/"submission.zip"
    sealed = read(segment/"sealed.json")
    if sha(archive) != sealed["archive_sha256"]:
        raise ValueError("sealed submission hash mismatch")
    receipt = read(root/"operator/verified.json")
    with zipfile.ZipFile(archive) as z:
        def take(name):
            found = [p for p in z.namelist() if PurePosixPath(p).name == name]
            if len(found)!=1:
                raise ValueError("missing or ambiguous "+name)
            return z.read(found[0])
        profile = take("profile.csv")
        if hashlib.sha256(profile).hexdigest()!=receipt["profile_sha256"] or json.loads(take("receipt.json"))!=receipt:
            raise ValueError("receipt or native profile mismatch")
        if json.loads(take("case.json"))!=read(root/"operator/input/case.json"):
            raise ValueError("sealed matrix differs from node input")
        summary = json.loads(take("summary.json"))
        readme = take("README.md").decode("utf-8-sig")
    points = list(csv.DictReader(io.StringIO(profile.decode("ascii"))))
    y = [float(row["r_m"]) for row in points]
    u = [float(row["u_m_s"]) for row in points]
    if len(points)!=65 or any(abs(v-i*.01/64)>1e-12 for i,v in enumerate(y)) or not all(map(math.isfinite,u+y)):
        raise ValueError("invalid node grid or velocity")
    error = max(abs(speed-(-.02+10*pos)) for pos,speed in zip(y,u))
    integrated = sum((b-a)*(v+w)/2 for a,b,v,w in zip(y,y[1:],u,u[1:]))
    shear = .002*(u[1]-u[0])/(y[1]-y[0])
    flow_error = abs(summary["flow_per_width_m2_s"]/.0003-1)
    shear_error = abs(summary["shear_xy_pa"]/.02-1)
    return dict(job=receipt["job_id"],nodes=65,max_velocity_error_m_s=error,
                independent_flow_per_width_m2_s=integrated,independent_shear_xy_pa=shear,
                submitted_flow_relative_error=flow_error,submitted_shear_relative_error=shear_error,
                readme_present=bool(readme.strip()),numerical_pass=error<=1e-8 and flow_error<=.001 and shear_error<=.001)


if __name__=="__main__":
    p = argparse.ArgumentParser()
    p.add_argument("arm",choices=ARMS)
    p.add_argument("--continuation",action="store_true")
    args = p.parse_args()
    result = verify(args.arm,args.continuation)
    print(json.dumps(result,indent=2))
    raise SystemExit(0 if result["numerical_pass"] else 1)
