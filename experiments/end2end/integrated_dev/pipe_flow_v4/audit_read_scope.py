"""Emit only categories, proof-of-return flags, and integrity hashes for reviewed trajectories."""
import hashlib
import json
from pathlib import Path

BASE=Path(__file__).resolve().parents[5]/"graduation-experiment-results/chapter3_end_to_end_evaluation/dsh/pipe_flow_paired_100_20261122"
CATEGORIES={10:"own parent directory inventory",11:"own prompt, provider overlay and attempt authorization",
            12:"own effective startup configuration",13:"own effective startup configuration",14:"own composed profile",
            **{i:"own native session events or derived views" for i in range(15,23)}}
def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def audit(arm):
    root=BASE/arm
    trace=root/"native_events.jsonl"
    calls={}
    results={}
    modes=set()
    presets=set()
    for line in trace.open(encoding="utf8"):
        event=json.loads(line)["event"]
        data=event.get("data",{})
        if event["type"]=="sandbox/mode":
            modes.add(data["mode"])
        if event["type"]=="permission/preset":
            presets.add(data["preset"])
        if event["type"]=="tool/call":
            calls[data["callId"]]=(data["step"],data["name"])
        if event["type"]=="tool/result":
            for part in data.get("message",{}).get("content",[]):
                if part.get("type")=="tool-result":
                    results[part["toolCallId"]]=dict(ok=not part.get("isError",False),text_returned=any(
                         x.get("type")=="text" and x.get("text") for x in part.get("content",[])))
    exposure=[]
    for key,(step,name) in calls.items():
        if arm=="general" and step in CATEGORIES:
            assert name=="pwsh" and results[key]=={"ok":True,"text_returned":True}
            exposure.append(dict(step=step,category=CATEGORIES[step],**results[key]))
    frozen=json.loads((BASE/"index.json").read_bytes())
    original=next(r for r in frozen["rows"] if r["arm"]==arm)
    assert digest(root/"submission.zip")==original["submission_sha256"]
    assert digest(root/"provider_ledger/ledger.json")==original["ledger_sha256"]
    return dict(arm=arm,trace_sha256=digest(trace),tool_calls_reviewed=len(calls),
                sandbox_mode=sorted(modes),permission_preset=sorted(presets),parent_reads_or_listings=exposure,
                verified_seal_sha256=original["submission_sha256"],verified_ledger_sha256=original["ledger_sha256"])

if __name__=="__main__":
    print(json.dumps(dict(arms=[audit(a) for a in ("general","professional")],method="Retrospective classification of the two specific traces after reviewing tool arguments and paired results. No raw commands, paths, returned text or configuration values exported."),indent=2))
