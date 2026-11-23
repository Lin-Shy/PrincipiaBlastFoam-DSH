"""A post-hoc calculator for the old profile's generic Python-via-shell capability."""
import json
import math
import sys
from pathlib import Path

settings=json.loads(Path("settings.json").read_bytes())
records=json.loads(Path("records.json").read_bytes())
kind=sys.argv[1]
terminal=True
if kind=="pipe":
    terms=[math.pi*(r["outer_mm"]**2-r["inner_mm"]**2)*r["u_m_s"]*1e-3 for r in records]
    amount=sum(terms)
elif kind=="coverage":
    lo,hi=settings["window"]
    cuts=sorted({lo,hi,*[x for r in records for x in [r["start"],r["end"]] if lo<x<hi]})
    terms=[0.0]*len(records)
    amount=0
    for left,right in zip(cuts,cuts[1:]):
        for i,r in enumerate(records):
            if r["valid"] and r["start"]<=left and right<=r["end"]:
                terms[i]+=right-left
                break
        else:
            amount+=right-left
elif kind=="restart":
    job=settings["job"]
    attempt=max(r["attempt"] for r in records if r["job"]==job)
    times=set()
    terms=[]
    state=None
    for r in records:
        chosen=(r["job"],r["attempt"])==(job,attempt)
        fresh=chosen and r["event"]=="WRITE" and r["time_s"] not in times
        if fresh:
            times.add(r["time_s"])
        if chosen and r["event"] in ("FAIL","DONE"):
            state=r["event"]
        terms.append(int(fresh))
    amount=len(times)
    terminal=state=="DONE"
else:
    raise ValueError(kind)
report=dict(terms=terms,amount=amount,decision="release" if terminal and settings["band"][0]<=amount<=settings["band"][1] else "hold")
with Path("old-shell-calculation.json").open("x",encoding="utf8") as f:
    json.dump(report,f,allow_nan=False)
