"""Recompute the selected public tasks using only the three dispatched JSON files."""
import argparse
import hashlib
import json
import math
import zipfile

from wave import ARMS,DATA,OUT,read,sha


def check(task,arm,segment=None):
    pair=OUT/task
    root=pair/arm
    attempt=root/segment if segment else root
    package=DATA/"packages"/(task+".zip")
    with zipfile.ZipFile(package) as z:
        config=json.loads(z.read("settings.json"))
        records=json.loads(z.read("records.json"))
    source_sha=sha(package)
    if source_sha!=read(pair/"manifest.json")["public_package_sha256"]:
        raise ValueError("changed input")
    receipt=read(attempt/"sealed.json")
    if sha(attempt/"submission.zip")!=receipt["archive_sha256"]:
        raise ValueError("changed submission")
    with zipfile.ZipFile(attempt/"submission.zip") as z:
        if "report.json" not in z.namelist():
            return dict(passed=False,reason="report.json missing",files=z.namelist())
        report=json.loads(z.read("report.json"))
    if not isinstance(report,dict):
        return dict(passed=False,reason="report.json must contain an object")
    def number(value):
        return type(value) in (int,float) and math.isfinite(value)
    family=next(t["family"] for t in read(DATA/"READY.json")["tasks"] if t["id"]==task)
    if family=="duct":
        if not number(report.get("mean_m_s")):
            return dict(passed=False,reason="mean_m_s must be finite")
        field=report["field_m_s"]
        nx,ny=config["nx"],config["ny"]
        if len(field)!=ny+1 or not all(len(row)==nx+1 and all(type(v) in (int,float) and math.isfinite(v) for v in row) for row in field):
            return dict(passed=False,reason="invalid field shape or values")
        boundary=max(abs(field[j][i]) for j in range(ny+1) for i in range(nx+1) if j in (0,ny) or i in (0,nx))
        dx=config["width_m"]/nx
        dy=config["height_m"]/ny
        source=config["pressure_gradient_Pa_m"]/config["viscosity_Pa_s"]
        residual=max(abs((2*field[j][i]-field[j][i-1]-field[j][i+1])/dx**2+
                         (2*field[j][i]-field[j-1][i]-field[j+1][i])/dy**2-source)
                     for j in range(1,ny) for i in range(1,nx))
        mean=sum(field[j][i]*(.5 if i in (0,nx) else 1)*(.5 if j in (0,ny) else 1)
                 for j in range(ny+1) for i in range(nx+1))/(nx*ny)
        native=read(root/"operator/verified.json")
        actual=hashlib.sha256(json.dumps(field,separators=(",",":"),allow_nan=False).encode()).hexdigest()
        owned=(str(report["job_id"])==native["job_id"] and native["package_sha256"]==source_sha and
               actual==native["field_sha256"] and native["scheduler"]=="COMPLETED")
        mean_error=abs(report["mean_m_s"]-mean)
        return dict(passed=owned and boundary<=1e-10 and residual<=1e-7 and mean_error<=1e-8,
                    verified_node=owned,job=native["job_id"],boundary_max=boundary,residual_max=residual,
                    computed_mean=mean,mean_error=mean_error)
    terminal_ok=True
    if family=="cavity":
        expected=[r["u"]*r["dx"]+r["v"]*r["dy"] if r["contour"]==config["contour"] else 0 for r in records]
        amount=sum(expected)
    elif family=="pipe":
        expected=[math.pi*(r["outer_mm"]**2-r["inner_mm"]**2)*r["u_m_s"]/1000 for r in records]
        amount=sum(expected)
    elif family=="coverage":
        lo,hi=config["window"]
        pieces=sorted({lo,hi,*(max(lo,min(hi,r[k])) for r in records for k in ("start","end"))})
        spans=list(zip(pieces,pieces[1:]))
        covered=set()
        expected=[]
        for r in records:
            hit={s for s in spans if r["valid"] and r["start"]<=s[0] and r["end"]>=s[1]}
            expected.append(sum(b-a for a,b in hit-covered))
            covered.update(hit)
        amount=hi-lo-sum(expected)
    elif family=="restart":
        attempt=max(r["attempt"] for r in records if r["job"]==config["job"])
        seen=set()
        expected=[]
        terminal_ok=False
        for r in records:
            chosen=r["job"]==config["job"] and r["attempt"]==attempt
            fresh=chosen and r["event"]=="WRITE" and r["time_s"] not in seen
            expected.append(int(fresh))
            if fresh:
                seen.add(r["time_s"])
            if chosen and r["event"]=="DONE":
                terminal_ok=True
        amount=len(seen)
    elif family=="balance":
        litres={"L":1.0,"mL":.001}
        expected=[r["delta"]*litres[r["unit"]]*(1 if r["direction"]=="IN" else -1) if r["accepted"] else 0
                  for r in records]
        amount=config["final_L"]-config["initial_L"]-sum(expected)
    else:
        raise ValueError("unexpected selected task")
    terms=report["terms"]
    if not number(report.get("amount")) or not isinstance(terms,list) or not all(number(t) for t in terms):
        return dict(passed=False,reason="amount and terms must be numeric and finite")
    match=len(terms)==len(expected) and all(abs(a-b)<=1e-8 for a,b in zip(terms,expected))
    decision="release" if terminal_ok and config["band"][0]<=amount<=config["band"][1] else "hold"
    evidence=report.get("evidence")
    cites=all(n in json.dumps(evidence,ensure_ascii=False) for n in ("records.json","settings.json"))
    return dict(passed=match and abs(report["amount"]-amount)<=1e-8 and report["decision"]==decision and cites,
                independent_amount=amount,independent_terms=expected,expected_decision=decision,
                reported_amount=report["amount"],reported_terms=terms,reported_decision=report["decision"],sources_named=cites)


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("task")
    p.add_argument("arm",choices=ARMS)
    p.add_argument("--segment")
    a=p.parse_args()
    print(json.dumps(check(a.task,a.arm,a.segment),indent=2))
