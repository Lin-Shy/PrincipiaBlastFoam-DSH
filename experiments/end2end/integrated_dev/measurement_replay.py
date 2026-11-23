"""Replay the three exposed failure modes through native DSH tool dispatch."""
import json
import math
from pathlib import Path
import subprocess
import sys
import zipfile
sys.path.insert(0, str(Path(__file__).resolve().parent / "expansion"))
import wave
from measurement_profile import HERE, PLUGIN

OUT = wave.OUT.parent / "measurement_diagnostic_20261122"
DATA = wave.DATA
read, sha, write = wave.read, wave.sha, wave.write


def reproduce(item):
    task = item["id"]
    source = DATA / item["archive"]
    arm = wave.OUT / task / "professional"
    frozen = read(arm / "public_score.json")
    assert not frozen["passed"] and sha(source) == frozen["public_sha256"]
    assert sha(arm / "submission.zip") == frozen["submission_sha256"]
    target = OUT / "replay" / task
    target.mkdir(parents=True)
    with zipfile.ZipFile(arm / "submission.zip") as submission:
        old = json.loads(submission.read("report.json"))
    with zipfile.ZipFile(source) as package:
        rows = json.loads(package.read("records.json"))
        settings = json.loads(package.read("settings.json"))
    family = item["family"]
    if family == "pipe":
        name = "convert_volume_rates"
        values = [math.pi*((r["outer_mm"]/1000)**2-(r["inner_mm"]/1000)**2)*r["u_m_s"] for r in rows]
        params = dict(values=values, **{"from":"m3/s","to":"L/s"})
    elif family == "coverage":
        name = "interval_coverage"
        params = dict(window=settings["window"], intervals=[[r["start"],r["end"]] if r["valid"] else None for r in rows])
    elif family == "restart":
        name = "latest_attempt_events"
        params = dict(job=settings["job"], events=[dict(r,time=r["time_s"]) for r in rows],
                      writeEvent="WRITE", terminalEvents=["DONE","FAIL"])
    else:
        raise ValueError(family)
    args = target / "args.json"
    write(args, dict(input=json.dumps(params)))
    proc = subprocess.run([sys.executable,str(HERE/"start.py"),"professional",str(target),"invoke",name,
                          "--args-file",str(args)], capture_output=True, encoding="utf8", errors="replace")
    (target/"stdout.txt").write_text(proc.stdout,encoding="utf8")
    (target/"stderr.txt").write_text(proc.stderr,encoding="utf8")
    proc.check_returncode()
    log = json.loads(proc.stdout.strip().splitlines()[-1])
    assert name in log["tools"] and "measurement-review" in log["skills"]
    result = json.loads(log["calls"][0]["result"]["content"][0]["text"])
    terminal = True
    if family == "pipe":
        terms = result["values"]
        amount = sum(terms)
    elif family == "coverage":
        terms, amount = result["increments"], result["uncovered"]
    else:
        terms, amount = result["increments"], result["distinct"]
        terminal = result["terminal"] == "DONE"
    decision = "release" if terminal and settings["band"][0] <= amount <= settings["band"][1] else "hold"
    assert math.isclose(amount,frozen["independent_amount"],abs_tol=1e-8)
    assert len(terms)==len(rows) and all(math.isclose(a,b,abs_tol=1e-8) for a,b in zip(terms,frozen["independent_terms"]))
    assert decision == frozen["expected_decision"]
    write(target/"comparison.json",dict(public_package_sha256=sha(source),old_archive_sha256=sha(arm/"submission.zip"),
          old=old,native_tool=result,reconstructed=dict(terms=terms,amount=amount,decision=decision),passed=True,
          model_requests=0,tool_sha256=sha(PLUGIN)))


if __name__=="__main__":
    items = read(DATA/"READY.json")["tasks"]
    for item in items:
        if not read(wave.OUT/item["id"]/"professional/public_score.json")["passed"]:
            reproduce(item)

