"""Independent numeric and provenance checks on a sealed ordinary-fluid PIPE-01 project."""
import csv
import hashlib
import io
import json
import math
import tarfile
import zipfile
from run import ARMS, PAIR, read, sha, write, validate


def review(arm):
    root=PAIR/arm
    seal=read(root/"sealed.json")
    archive=root/"submission.zip"
    assert sha(archive)==seal["archive_sha256"]
    ledger=read(root/"provider_ledger/ledger.json")
    assert len(ledger["events"])==seal["requests"]<=ledger["max_requests"]==50
    operator=root/"operator"
    native=None
    if (operator/"verified.json").is_file():
        native=read(operator/"verified.json")
        assert native["scheduler"]=="COMPLETED" and native["nodes"]=="1"
        assert sha(operator/"collected.tar")==native["archive_sha256"]
        assert sha(operator/"input/case.json")==native["case_sha256"]
        with tarfile.open(operator/"collected.tar") as z:
            assert z.extractfile("./logs/pipeline.exit").read().strip()==b"0"
            assert z.extractfile("./logs/allocated_job_id.txt").read().decode().strip()==native["job_id"]
            profile=z.extractfile("./profile.csv").read()
        assert hashlib.sha256(profile).hexdigest()==native["profile_sha256"]
    result=dict(seal=seal,native=native)
    with zipfile.ZipFile(archive) as z:
        names=z.namelist()
        assert all(hashlib.sha256(z.read(n)).hexdigest()==seal["files"][n] for n in names)
        result["files"]=names
        def take(name):
            found=[p for p in names if p.split("/")[-1].lower()==name.lower()]
            return z.read(found[0]) if len(found)==1 else None
        result["readme"]=take("README.md") is not None
        raw_case=take("case.json")
        if raw_case:
            case=json.loads(raw_case.decode("utf-8-sig"))
            validate(case)
            result["matrix_matches_node"]=bool(native and case==read(operator/"input/case.json"))
        submitted=take("profile.csv")
        result["profile_matches_node"]=bool(native and submitted==profile)
        result["receipt_matches_node"]=bool(native and any(json.loads(z.read(n).decode("utf-8-sig"))==native for n in names if n.lower().endswith(".json") and "receipt" in n.lower()))
        raw_summary=take("summary.json")
        summary=json.loads(raw_summary.decode("utf-8-sig")) if raw_summary else {}
    if native:
        data=list(csv.DictReader(io.StringIO(profile.decode("ascii"))))
        radius=[float(d["r_m"]) for d in data]
        speed=[float(d["u_m_s"]) for d in data]
        assert len(data)==65 and all(abs(r-.01*i/64)<=1e-12 for i,r in enumerate(radius))
        assert all(math.isfinite(u) for u in speed)
        reference=[.8*(.01**2-r**2)/(4*.001) for r in radius]
        flow=math.pi*math.fsum((b-a)*(a*u+b*v) for a,b,u,v in zip(radius,radius[1:],speed,speed[1:]))
        exact=math.pi*.8*.01**4/(8*.001)
        error=max(abs(u-v) for u,v in zip(speed,reference))
        result["numerical"]=dict(center=speed[0],max_error_m_s=error,flow_m3_s=flow,exact_flow_m3_s=exact,
            relative_error=abs(flow/exact-1),node_field_pass=error<=.0001 and abs(flow/exact-1)<=.01,
            submitted_summary=summary,summary_pass=(abs(summary.get("center_m_s",math.inf)-speed[0])<=1e-8 and abs(summary.get("flow_m3_s",math.inf)/exact-1)<=.01))
    write(root/"numeric_review.json",result)
    return result


if __name__=="__main__":
    import sys
    review(sys.argv[1])
