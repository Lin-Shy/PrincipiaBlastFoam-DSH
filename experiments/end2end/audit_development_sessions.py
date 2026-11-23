"""Summarize native DSH usage, including compaction and failed startup attempts."""
from collections import Counter
import argparse
import json
import hashlib
import io
import os
from pathlib import Path
import zstandard


def read_events(path):
    """Read every concatenated zstd frame; malformed evidence must fail loudly."""
    with path.open("rb") as source, zstandard.ZstdDecompressor().stream_reader(source) as stream:
        return [json.loads(line) for line in io.TextIOWrapper(stream, encoding="utf-8") if line.strip()]


def numeric_usage(value):
    return {k: v for k, v in (value or {}).items()
            if isinstance(v, (int, float)) and not isinstance(v, bool)}


def audit(events):
    """Count native events, never nested copies in tool output or request context."""
    tools, usage, characters = Counter(), Counter(), Counter()
    calls, skills, ends = {}, set(), []
    results = errors = retries = 0
    for event in events:
        kind, data = event.get("type"), event.get("data", {})
        if kind == "assistant/message":
            usage.update(numeric_usage(data.get("usage")))
        elif kind == "tool/call":
            name = data.get("name", "unknown")
            tools[name] += 1
            calls[data.get("callId")] = name
            if name == "skill":
                args = data.get("arguments", {})
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                if isinstance(args, dict) and isinstance(args.get("name"), str):
                    skills.add(args["name"])
        elif kind == "tool/result":
            for block in data.get("message", {}).get("content", []):
                if block.get("type") != "tool-result":
                    continue
                results += 1
                errors += bool(block.get("isError"))
                name = calls.get(block.get("toolCallId"), "unknown")
                characters[name] += sum(len(c.get("text", "")) for c in block.get("content", [])
                                        if c.get("type") == "text")
        elif kind == "llm/retry":
            retries += 1
        elif kind == "turn/end":
            ends.append(data.get("reason"))
    return {"events": len(events), "tool_calls": sum(tools.values()), "tools": dict(tools),
            "tool_results": results, "tool_errors": errors, "loaded_skills": sorted(skills),
            "all_tool_text_characters": sum(characters.values()), "tool_text_characters": dict(characters),
            "reported_usage": dict(usage), "llm_retries": retries, "turn_end": ends}


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
        summary["source_relative_path"] = file.relative_to(root).as_posix()
        summary["source_sha256"] = hashlib.sha256(file.read_bytes()).hexdigest()
        summaries.append(summary)
        totals.update(summary["reported_usage"])
        totals.update(compaction)
    return {"sessions": summaries, "reported_usage_including_compaction": dict(totals),
            "actual_cost": None,
            "scope": "Provider-reported assistant and compaction usage across all native sessions; failed/unreported request usage may be missing. Cache and reasoning fields are components and must not be added to totalTokens again. No price was assumed."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--output", type=Path, help="New derived report; existing evidence is never overwritten")
    args = parser.parse_args()
    result = summarize(args.run_dir)
    output = args.output or args.run_dir / "session_audit.json"
    with output.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"sessions": len(result["sessions"]), "reported_usage_including_compaction": result["reported_usage_including_compaction"]}, ensure_ascii=False))
