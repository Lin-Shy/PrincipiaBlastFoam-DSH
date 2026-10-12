"""同一冻结语料/构建器，仅切换本地include字典解析；不读取评测题。"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text())


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+"\n")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--baseline-skill", type=Path, required=True)
    p.add_argument("--candidate-builder", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    summaries, graphs = {}, {}
    for name, enabled in (("includes_off", False), ("includes_on", True)):
        skill = args.output / name / "skill"
        shutil.copytree(args.baseline_skill, skill, ignore=shutil.ignore_patterns("__pycache__", "cache"))
        shutil.copy2(args.candidate_builder, skill/"scripts/knowledge.py")
        # Both arms use the same candidate source file; only this flag differs.
        command = [sys.executable, str(skill/"scripts/build.py")]
        if enabled:
            command.append("--parse-included-dictionaries")
        begin = time.monotonic()
        response = subprocess.run(command, capture_output=True, text=True, check=True)
        elapsed = time.monotonic()-begin
        result = json.loads(response.stdout)
        current = read(skill/"index/current.json")["snapshot"]
        graph = read(skill/"index/releases"/current/"graph.json")
        manifest = read(skill/"index/releases"/current/"manifest.json")
        graphs[name] = {n["id"]: n for n in graph["nodes"]}
        counts = Counter(n["kind"] for n in graph["nodes"])
        byfile = Counter(n["evidence"]["path"] for n in graph["nodes"] if n["kind"] == "configuration")
        summaries[name] = {"snapshot": current, "builder_sha256": digest(skill/"scripts/knowledge.py"),
            "parse_included_dictionaries": enabled, "elapsed_seconds": elapsed, "build": result,
            "node_kinds": dict(counts), "configurations_by_file": dict(byfile),
            "literal_include_targets": manifest["literal_include_targets"],
            "source_inventory": manifest["inventory"], "model_calls": 0, "model_tokens": 0}
        save(args.output/name/"construction.json", summaries[name])
    if summaries["includes_off"]["source_inventory"] != summaries["includes_on"]["source_inventory"]:
        raise ValueError("ablation corpus mismatch")
    before, after = graphs["includes_off"], graphs["includes_on"]
    added = [n for uid,n in after.items() if uid not in before and n["kind"] == "configuration"]
    removed = [uid for uid in before if uid not in after]
    if removed:
        raise ValueError("include extension unexpectedly removed base nodes")
    audit = []
    for node in added:
        ev=node["evidence"]
        path=args.output/"includes_on/skill/corpus"/ev["path"]
        lines=path.read_text().splitlines()
        if digest(path) != ev["sha256"] or not 1 <= ev["line_start"] <= ev["line_end"] <= len(lines):
            raise ValueError("new node evidence mismatch")
        audit.append({"id":node["id"],"dictionary_path":node["dictionary_path"],"value":node["value"],
                      "evidence":ev,"raw":"\n".join(lines[ev["line_start"]-1:ev["line_end"]]),
                      "status":node["evidence_status"],"scope_note":node["scope_note"]})
    save(args.output/"added-configurations.json",audit)
    summary = {"hypothesis":"Parsing dictionary-reachable literal include fragments recovers reusable parameter scopes missed by file-name/header classification.",
        "single_factor":"parse_included_dictionaries false versus true; same source bytes, builder, parser, search, prompts and budgets",
        "added_configuration_count":len(added), "added_files":dict(Counter(n["evidence"]["path"] for n in added)),
        "removed_nodes":removed, "source_identity_equal":True,
        "builder_sha256":summaries["includes_on"]["builder_sha256"],
        "construction_seconds":{k:v["elapsed_seconds"] for k,v in summaries.items()},
        "scope":"Deterministic structure recovery only. No answer quality or speedup claim; no effective override resolution or physics compatibility proof.",
        "frozen_files":{p.relative_to(args.output).as_posix():digest(p) for p in sorted(args.output.rglob("*"))
                        if p.is_file() and "__pycache__" not in p.parts and "cache" not in p.parts}}
    save(args.output/"ablation.json",summary)
    print(json.dumps({k:v for k,v in summary.items() if k!="frozen_files"},ensure_ascii=False))


if __name__ == "__main__":
    main()
