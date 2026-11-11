"""Summarize native DSH usage, including compaction and failed startup attempts."""
from collections import Counter
import argparse
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "retrieval_method"))
from audit_native_session import read_events, audit


def summarize(run):
    root = run.resolve() / "runtime/home/sessions"
    if os.name == "nt":
        root = Path("\\\\?\\" + str(root))
    summaries = []
    totals = Counter()
    for file in root.rglob("session.v2.jsonl.zstd"):
        events = read_events(file)
        summary = audit(events)
        compaction = Counter()
        for event in events:
            if event["type"] == "compaction/summary":
                compaction.update({k: v for k, v in (event.get("data", {}).get("usage") or {}).items()
                                   if isinstance(v, (int, float)) and not isinstance(v, bool)})
        summary["compaction_reported_usage"] = dict(compaction)
        summaries.append(summary)
        totals.update(summary["reported_usage"])
        totals.update(compaction)
    return {"sessions": summaries, "reported_usage_including_compaction": dict(totals),
            "actual_cost": None,
            "scope": "Provider-reported assistant and compaction usage across all native sessions; failed/unreported request usage may be missing. Cache and reasoning fields are components and must not be added to totalTokens again. No price was assumed."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()
    result = summarize(args.run_dir)
    (args.run_dir / "session_audit.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"sessions": len(result["sessions"]), "reported_usage_including_compaction": result["reported_usage_including_compaction"]}, ensure_ascii=False))
