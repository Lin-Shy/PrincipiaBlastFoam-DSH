"""Prepare and run a holdout cohort only after the selected implementation gate exists."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import fcntl
import hashlib
import json
import os
from pathlib import Path
import random
import shutil
import time

import leaderboard_audit as audit
import graphify_qa as base
import navigation_qa as qa


BASELINE_GROUPS = {"control": ["no_graph"], "GN": ["graph_first"]}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path: Path):
    return json.loads(path.read_text())


def copy_file(source: Path, target: Path):
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def verify_gate(gate_path: Path):
    gate = read(gate_path)
    if not gate.get("implementation_frozen") or gate.get("holdout_opened"):
        raise ValueError("final implementation gate is not closed and frozen")
    if gate.get("model") != "deepseek-flash" or not gate.get("selection_rule_applied_without_holdout"):
        raise ValueError("invalid final selection gate")
    for item in gate["development_reports"].values():
        if sha(Path(item["path"])) != item["sha256"]:
            raise ValueError("development report changed after final selection")
    for item in gate["dev_runs"].values():
        if sha(Path(item["path"]) / "protocol.json") != item["protocol_sha256"]:
            raise ValueError("development run protocol changed after final selection")
    selected = gate["selected"]
    source = Path(selected["source_run"])
    if sha(source / "protocol.json") != selected["source_protocol_sha256"]:
        raise ValueError("selected source protocol changed")
    if sha(source / selected["arm"] / "protocol.json") != selected["source_arm_protocol_sha256"]:
        raise ValueError("selected arm protocol changed")
    if sha(Path(__file__)) != gate["holdout_runner_sha256"]:
        raise ValueError("holdout runner changed after final selection")
    return gate


def verify_holdout_dataset(gate, dataset: Path):
    baseline_root = Path(gate["dev_runs"]["baseline"]["path"])
    dev_dataset = Path(read(baseline_root / "protocol.json")["parent_dataset"])
    dev_manifest = read(dev_dataset / "manifest.json")
    if Path(dev_manifest["parent_dataset"]).resolve() != dataset.resolve():
        raise ValueError("holdout is not the frozen parent of the development revision")
    if sha(dataset / "manifest.json") != dev_manifest["parent_manifest_sha256"]:
        raise ValueError("holdout parent manifest changed")
    parent = read(dataset / "manifest.json")
    expected = dev_manifest["parent_holdout_artifact_sha256"]
    for name in ("holdout.questions.json", "holdout.annotations.json"):
        if parent["artifacts"].get(name) != expected[name] or sha(dataset / name) != expected[name]:
            raise ValueError("frozen holdout artifact changed: " + name)
    if sha(dataset / "scoring-rules.json") != parent["artifacts"]["scoring-rules.json"]:
        raise ValueError("holdout scoring rules changed")
    return parent


def copy_arm(source: Path, target: Path, questions: Path, annotations: Path,
             scoring: Path, arm_name: str, methods, dataset_sha: str):
    source_protocol = read(source / "protocol.json")
    target.mkdir(parents=True)
    replaced = {"questions.json", "evaluation_only/annotations.json",
                "evaluation_only/scoring-rules.json"}
    for name, expected in source_protocol["files"].items():
        path = source / name
        if sha(path) != expected:
            raise ValueError("selected static arm file changed: " + name)
        if name not in replaced:
            copy_file(path, target / name)
    copy_file(questions, target / "questions.json")
    copy_file(annotations, target / "evaluation_only/annotations.json")
    copy_file(scoring, target / "evaluation_only/scoring-rules.json")
    protocol = {**source_protocol, "arm": arm_name, "methods": list(methods),
                "split": "holdout", "replicates": 3,
                "dataset_manifest_sha256": dataset_sha,
                "source_development_arm_protocol_sha256": sha(source / "protocol.json"),
                "quality_status": "unscored holdout; source-grounded review required"}
    protocol["files"] = {p.relative_to(target).as_posix(): sha(p)
                         for p in sorted(target.rglob("*")) if p.is_file()}
    (target / "protocol.json").write_text(json.dumps(protocol, ensure_ascii=False, indent=2) + "\n")


def copy_runtime(source_root: Path, output: Path):
    for path in source_root.glob("*.py"):
        copy_file(path, output / path.name)
    copy_file(Path(__file__), output / "runner.py")


def prepare(args):
    output = args.run.resolve()
    if output.exists():
        raise FileExistsError("preserve the first holdout cohort")
    gate_path = args.gate.resolve()
    gate = verify_gate(gate_path)
    dataset = args.dataset.resolve()
    parent_manifest = verify_holdout_dataset(gate, dataset)
    output.mkdir(parents=True)
    baseline_root = Path(gate["dev_runs"]["baseline"]["path"])
    selected = gate["selected"]
    if args.kind == "baseline":
        source_root = baseline_root
        groups = BASELINE_GROUPS
        for arm, methods in groups.items():
            copy_arm(source_root / arm, output / arm, dataset / "holdout.questions.json",
                     dataset / "holdout.annotations.json", dataset / "scoring-rules.json",
                     arm, methods, sha(dataset / "manifest.json"))
    else:
        if selected["source"] == "baseline":
            raise ValueError("selected final method is already in the baseline holdout cohort")
        source_root = Path(selected["source_run"])
        arm = selected["arm"]
        groups = {arm: [selected["method"]]}
        copy_arm(source_root / arm, output / arm, dataset / "holdout.questions.json",
                 dataset / "holdout.annotations.json", dataset / "scoring-rules.json",
                 arm, groups[arm], sha(dataset / "manifest.json"))
        shutil.copytree(source_root / "hybrid", output / "hybrid")
        source_arm_protocol = read(source_root / arm / "protocol.json")
        graph = (source_root / source_arm_protocol["graph"] if "graph" in source_arm_protocol
                 else source_root / "candidate-graph.json")
        copy_file(graph, output / "selected-graph.json")
    copy_runtime(source_root, output)
    questions = read(dataset / "holdout.questions.json")
    protocol_source = read(source_root / "protocol.json")
    protocol = {
        "schema": "chapter2-frozen-final-holdout-v1",
        "kind": args.kind,
        "groups": groups,
        "replicates": 3,
        "model": "deepseek-flash",
        "shuffle_seed": 20260910,
        "limits": {"decisions": 8, "per_tool_characters": 6000,
                   "returned_characters": 24000},
        "max_generated_tokens": 8000,
        "max_model_calls": 9,
        "planned_sessions": len(questions) * 3 * sum(map(len, groups.values())),
        "corpus_id": protocol_source["corpus_id"],
        "runtime_identity": protocol_source["runtime_identity"],
        "graphify_identity": protocol_source.get("graphify_identity"),
        "holdout_unlocked": True,
        "holdout_manifest_sha256": sha(dataset / "manifest.json"),
        "holdout_questions_sha256": parent_manifest["artifacts"]["holdout.questions.json"],
        "holdout_annotations_sha256": parent_manifest["artifacts"]["holdout.annotations.json"],
        "implementation_gate": str(gate_path),
        "implementation_gate_sha256": sha(gate_path),
        "selected": selected,
        "selected_options": read(source_root / selected["arm"] / "protocol.json").get("options")
                            if args.kind == "candidate" else None,
        "failure_policy": "same frozen at-most-nine identical-request transport attempts; four consecutive no-HTTP network errors stop the batch; no answer-quality retries",
        "ranking_gate": "complete grid, exact model identity, zero-model replay and source-grounded review",
        "statistics": "holdout reported separately; equal-weight categories and paired fact-family uncertainty",
    }
    protocol["files"] = {p.relative_to(output).as_posix(): sha(p)
                         for p in sorted(output.rglob("*")) if p.is_file()}
    (output / "protocol.json").write_text(json.dumps(protocol, ensure_ascii=False, indent=2) + "\n")
    audit.verify(output)
    print(json.dumps({"prepared": str(output), "kind": args.kind,
                      "planned_sessions": protocol["planned_sessions"]}, ensure_ascii=False))


def run_one(engine, runner, question, method, key, replicate, replay):
    return runner(engine, question, method, key, replicate, replay)


def execute(args):
    root = args.run.resolve()
    protocol = audit.verify(root)
    base.verify_runtime(protocol)
    if Path(__file__).resolve() != root / "runner.py":
        raise ValueError("execute the frozen holdout runner")
    base.SECRET = args.key_file.read_text().strip() if args.key_file else ""
    base.reset_transport_circuit()
    with (root / "runtime.lock").open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if protocol["kind"] == "baseline":
            import retrieval_leaderboard as leaderboard
            if protocol.get("graphify_identity"):
                base.verify(root)
            leaderboard.install()
            engines = {arm: base.Engine(root / arm, arm) for arm in protocol["groups"]}
            runners = {arm: base.run_one for arm in protocol["groups"]}
        else:
            import candidate_qa as candidate
            qa.write = base.save
            qa.instrument_file_reads()
            arm = next(iter(protocol["groups"]))
            engines = {arm: candidate.Engine(root / arm, arm, root / "hybrid",
                                              root / "selected-graph.json",
                                              protocol["selected_options"])}
            runners = {arm: candidate.run_one}
        questions = read(root / next(iter(protocol["groups"])) / "questions.json")
        jobs = [(arm, q, method, rep) for q in questions
                for rep in range(1, protocol["replicates"] + 1)
                for arm, methods in protocol["groups"].items() for method in methods]
        random.Random(protocol["shuffle_seed"]).shuffle(jobs)
        state = {"pid": os.getpid(), "command": args.command, "jobs": len(jobs),
                 "completed": 0, "errors": []}
        journal = root / "invocations" / f"{time.time_ns()}.json"
        audit.save(journal, {**state, "state": "running"})
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            pending = {}
            for arm, question, method, replicate in jobs:
                name = f"{question['id']}--{method}--r{replicate}"
                if args.command == "run" and (root / arm / "sessions" / name / "result.json").exists():
                    state["completed"] += 1
                    continue
                future = pool.submit(run_one, engines[arm], runners[arm], question, method,
                                     base.SECRET or None, replicate, args.command == "replay")
                pending[future] = arm + "/" + name
            for future in as_completed(pending):
                try:
                    result = future.result()
                    state["completed"] += 1
                    print("DONE", pending[future], result["status"], flush=True)
                except Exception as error:
                    state["errors"].append({"session": pending[future],
                                             "error_type": type(error).__name__})
                    print("ERROR", pending[future], type(error).__name__, flush=True)
                audit.save(journal, {**state, "state": "running"})
        outage = any(row["error_type"] == "GlobalTransportOutage" for row in state["errors"])
        audit.save(journal, {**state, "state": "network_circuit_open" if outage else "finished"})
        audit.verify(root)
        if outage:
            raise SystemExit(75)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument("command", choices=("prepare", "verify", "run", "replay"))
    cli.add_argument("--run", type=Path, required=True)
    cli.add_argument("--kind", choices=("baseline", "candidate"))
    cli.add_argument("--gate", type=Path)
    cli.add_argument("--dataset", type=Path)
    cli.add_argument("--key-file", type=Path)
    cli.add_argument("--workers", type=int, default=4)
    args = cli.parse_args()
    if args.command == "prepare":
        if not args.kind or not args.gate or not args.dataset:
            cli.error("prepare requires --kind, --gate and --dataset")
        prepare(args)
    elif args.command == "verify":
        audit.verify(args.run.resolve())
        print("PASS: frozen final holdout cohort")
    else:
        execute(args)


if __name__ == "__main__":
    main()
