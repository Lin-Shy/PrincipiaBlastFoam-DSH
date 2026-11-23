"""Verify the four sealed archives, recompute public fields and reconcile usage."""
import collections
import json
import math
from pathlib import Path
import subprocess
import sys
import zipfile
from measurement_annular_live import BATCH, OUT, ORDER, DATA, PROTOCOL, sha, read, write


def verify(task,revision):
    pair=BATCH/task/revision
    root=pair/"professional"
    seal=read(root/"sealed.json")
    assert sha(root/"submission.zip")==seal["archive_sha256"]
    assert sha(root/"provider_ledger/ledger.json")==seal["ledger_sha256"]
    manifest=read(pair/"manifest.json")
    assert all(sha(Path(p))==h for p,h in manifest["source_sha256"].items())
    assert all(sha(DATA/p)==h for p,h in manifest["item"]["judge"].items())
    grant=read(root/"attempt_intent.json")["authorization"]
    assert sha(pair/"manifest.json")==grant["pair_manifest_sha256"] and grant["max_requests_per_arm"]==12
    ledger=read(root/"provider_ledger/ledger.json")
    events=ledger["events"]
    assert ledger["max_requests"]==12 and len(events)==seal["requests"]<=12
    assert sum(e["usage"]["total_tokens"] for e in events if e.get("usage"))==seal["tokens_reported"]
    sources=OUT/"public_inputs"/task
    rows=read(sources/"records.json")
    band=read(sources/"settings.json")["band"]
    terms=[math.pi*(r["outer_mm"]-r["inner_mm"])*(r["outer_mm"]+r["inner_mm"])*r["u_m_s"]*1e-3 for r in rows]
    amount=math.fsum(terms)
    decision="release" if band[0]<=amount<=band[1] else "hold"
    def matches(value,expected):
        return type(value) in (float,int) and math.isfinite(value) and abs(value-expected)<=1e-8
    calls=collections.Counter()
    for line in (root/"native_events.jsonl").read_text(encoding="utf8").splitlines():
        e=json.loads(line)["event"]
        if e["type"]=="tool/call":
            calls[e["data"]["name"]]+=1
    fields=dict.fromkeys(["terms","amount","decision","evidence"],False)
    with zipfile.ZipFile(root/"submission.zip") as z:
        names=z.namelist()
        if "report.json" in names:
            report_path=root/"sealed-report.json"
            raw=z.read("report.json")
            if report_path.exists():
                assert raw==report_path.read_bytes()
            else:
                report_path.write_bytes(raw)
            proc=subprocess.run([sys.executable,"-B",str(DATA/"pack.py"),"grade",task,str(report_path)],
                                capture_output=True,text=True)
            official=json.loads(proc.stdout)
            try:
                report=json.loads(raw.decode("utf-8-sig"))
            except (ValueError,UnicodeError):
                report=None
            if isinstance(report,dict):
                t=report.get("terms")
                evidence=report.get("evidence")
                fields=dict(terms=isinstance(t,list) and len(t)==len(terms) and all(matches(v,n) for v,n in zip(t,terms)),
                            amount=matches(report.get("amount"),amount),decision=report.get("decision")==decision,
                            evidence=isinstance(evidence,list) and all(isinstance(x,str) for x in evidence) and sorted(evidence)==["records.json","settings.json"])
            assert official["pass"]==all(fields.values())==(proc.returncode==0)
            if set(official["fields"])==set(fields):
                assert official["fields"]==fields
        else:
            official=dict(reason="missing report",**{"pass":False})
    return dict(task=task,revision=revision,seal=seal,files=names,official=official,independent_fields=fields,
                independent_expected=dict(terms=terms,amount=amount,decision=decision),tool_calls=dict(calls),
                session=read(root/"native_outcome.json") if (root/"native_outcome.json").exists() else None,
                provider_states=dict(collections.Counter(e["state"] for e in events)))


if __name__=="__main__":
    rows=[verify(t,v) for t,v in ORDER]
    assert len({r["session"]["session_id"] for r in rows if r["session"]})==4
    totals={key:sum(r["seal"][key] for r in rows) for key in ("requests","tokens_reported","unknown_usage","cluster_jobs")}
    assert totals["requests"]<=48
    write(BATCH/"index.json",dict(budget_sha256=sha(BATCH/"budget.json"),protocol_sha256=sha(PROTOCOL),
          verifier_sha256=sha(Path(__file__)),rows=rows,totals=totals,money=None))
    print(json.dumps([(r["task"],r["revision"],r["official"],r["seal"]["requests"],r["seal"]["tokens_reported"],r["tool_calls"].get("convert_volume_rates",0)) for r in rows]))
    print(totals)
