"""第2轮：同一公开题面、无模型的五消融原生排名与预算送达检查。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import time

from chapter2_production_guard import install

ARMS = {"full": {}, "no_cross": {"with_cross": False}, "no_scope": {"with_scope": False},
        "fixed_window": {"structured_read": False}, "node_scan": {"with_paths": False}}
RUNTIME = ("chapter2_native_dev_probe.py", "chapter2_graph_retriever.py", "chapter2_canonical_delivery.py",
           "canonical_evidence_v1.py", "chapter2_production_guard.py", "candidate_graph_utils.py",
           "index_free_graph_evidence.py", "candidate_paths.py")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    if path.exists():
        raise FileExistsError("new artifact version required")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+"\n")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=("prepare", "run"))
    for name in ("questions", "graph", "corpus", "corpus-manifest", "output"):
        p.add_argument("--"+name, type=Path, required=True)
    p.add_argument("--planner", type=Path)
    args = p.parse_args()
    if os.environ.get("PYTHONHASHSEED") != "0":
        raise ValueError("set PYTHONHASHSEED=0")
    guard = install(offline=True)
    questions = json.loads(args.questions.read_text())
    if any(q["split"] != "dev" for q in questions):
        raise ValueError("development public questions only")
    plans, plan_hashes, planner_sha = {}, {}, None
    if args.planner:
        planner_file = args.planner / "protocol.json"
        planner = json.loads(planner_file.read_text())
        if planner["model"] != "qwen3-8b" or planner["role"] != "common_query_planning_development":
            raise ValueError("fixed public development planner required")
        planner_sha = sha(planner_file)
        for q in questions:
            file = args.planner / "responses" / q["id"] / "compiled.json"
            value = json.loads(file.read_text())
            if value["question"] != q or value["protocol_sha256"] != planner_sha or value["response_sha256"] != sha(file.parent / "plan.json"):
                raise ValueError("public planning provenance drift")
            plans[q["id"]] = value["plan"]
            plan_hashes[q["id"]] = sha(file)
    runtime = Path(__file__).parent
    if args.command == "prepare":
        if args.output.exists():
            raise FileExistsError("new development version required")
        for name in RUNTIME:
            target = args.output / "runtime" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((runtime / name).read_bytes())
        save(args.output / "protocol.json", {"schema": "development-native-five-ablation-probe-v2", "major_round": 3,
             "questions": questions, "questions_sha256": sha(args.questions), "graph_sha256": sha(args.graph),
             "corpus_manifest_sha256": sha(args.corpus_manifest), "arms": ARMS,
             "runtime_sha256": {name: sha(runtime / name) for name in RUNTIME}, "guard": guard,
             "budgets": [6000, 12000, 24000], "planned_queries": len(questions)*len(ARMS),
             "query_policy": "unchanged public question + shared8B translation/needs" if args.planner else "unchanged public question only; no planner or answer model; no gold input",
             "planner_protocol_sha256": planner_sha, "plan_hashes": plan_hashes,
             "limits": "development mechanism check; no gold input or answer-model selection; not formal comparison"})
        return
    if runtime.resolve() != (args.output / "runtime").resolve():
        raise ValueError("run frozen runtime snapshot")
    protocol_file = args.output / "protocol.json"
    protocol = json.loads(protocol_file.read_text())
    if protocol["questions_sha256"] != sha(args.questions) or protocol["graph_sha256"] != sha(args.graph) or protocol["corpus_manifest_sha256"] != sha(args.corpus_manifest):
        raise ValueError("frozen input drift")
    if protocol["questions"] != questions or protocol["arms"] != ARMS:
        raise ValueError("public protocol drift")
    if protocol["planner_protocol_sha256"] != planner_sha or protocol["plan_hashes"] != plan_hashes:
        raise ValueError("frozen public plan drift")
    for name, expected in protocol["runtime_sha256"].items():
        if sha(runtime / name) != expected:
            raise ValueError("frozen runtime drift")
    from chapter2_graph_retriever import GraphRetriever
    from chapter2_canonical_delivery import canonicalize, render
    engines = {arm: GraphRetriever(args.graph, args.corpus, opts, args.corpus_manifest) for arm, opts in ARMS.items()}
    for q in questions:
        for arm, engine in engines.items():
            file = args.output / "responses" / q["id"] / (arm+".json")
            if file.exists():
                existing = json.loads(file.read_text())
                if existing["protocol_sha256"] != sha(protocol_file):
                    raise ValueError("existing response provenance mismatch")
                continue
            start = time.monotonic()
            ranked = engine.rank(q["question"], plans.get(q["id"]))
            read = engine.read_native(ranked)
            seconds = time.monotonic()-start
            units = canonicalize(read, seconds)
            deliveries = {str(b): render(units, b) for b in protocol["budgets"]}
            save(file, {"question": q, "arm": arm, "native": ranked, "canonical_units": units,
                        "deliveries": deliveries, "query_seconds": seconds, "load_seconds": engine.load_seconds,
                        "reading_seconds": read["reading_seconds"], "protocol_sha256": sha(protocol_file), "guard": guard})
            print("DONE", q["id"], arm, "seconds", round(seconds, 4), "units", len(units), flush=True)
    save(args.output / "completion.json", {"queries": len(questions)*len(ARMS), "model_calls": 0,
        "protocol_sha256": sha(protocol_file), "status": "complete"})


if __name__ == "__main__":
    main()
