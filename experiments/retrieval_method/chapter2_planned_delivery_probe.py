"""公共8B规划下的开发送达探针；不读取答案，不冒充纯原生排名榜。"""
import argparse
import hashlib
import json
import os
from pathlib import Path

from chapter2_production_guard import install


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    if path.exists():
        raise FileExistsError("new artifact version required")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+"\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "run"))
    for name in ("planner", "graph", "corpus", "output"):
        parser.add_argument("--"+name, type=Path, required=True)
    args = parser.parse_args()
    if os.environ.get("PYTHONHASHSEED") != "0":
        raise ValueError("set PYTHONHASHSEED=0")
    guard = install(offline=True)
    planner_protocol = json.loads((args.planner / "protocol.json").read_text())
    if planner_protocol["model"] != "qwen3-8b" or planner_protocol["role"] != "common_query_planning_development":
        raise ValueError("not frozen development public planning")
    questions_file = args.planner / "questions.json"
    if sha(questions_file) != planner_protocol["public_questions_sha256"]:
        raise ValueError("planner question drift")
    questions = json.loads(questions_file.read_text())
    plans, plan_hashes = {}, {}
    for q in questions:
        if q["split"] != "dev":
            raise ValueError("development only")
        file = args.planner / "responses" / q["id"] / "compiled.json"
        compiled = json.loads(file.read_text())
        response_file = file.parent / "plan.json"
        if compiled["question"] != q or compiled["protocol_sha256"] != sha(args.planner / "protocol.json") or compiled["response_sha256"] != sha(response_file):
            raise ValueError("public plan drift")
        plans[q["id"]] = compiled["plan"]
        plan_hashes[q["id"]] = {"compiled": sha(file), "response": sha(response_file), "status": compiled["status"]}
    runtime = Path(__file__).parent
    names = (Path(__file__).name, "chapter2_production_guard.py", "index_free_graph_evidence.py", "candidate_graph_utils.py", "candidate_paths.py")
    if args.command == "prepare":
        if args.output.exists():
            raise FileExistsError("new delivery probe version required")
        save(args.output / "protocol.json", {"schema": "development-common-plan-delivery-probe-v1", "major_round": 1,
             "graph_sha256": sha(args.graph), "planner_protocol_sha256": sha(args.planner / "protocol.json"), "plans": plan_hashes,
             "questions": questions, "arms": {"full": {"with_cross": True}, "no_cross": {"with_cross": False}},
             "return_character_cap": 24000, "guard": guard, "runtime_sha256": {name: sha(runtime / name) for name in names},
             "query_policy": "unchanged public question + shared translation; shared needs as slots; no answer/source choice model",
             "planned_queries": len(questions)*2, "model_calls_in_retrieval": 0,
             "limits": "legacy query packs groups under cap; assesses delivered original evidence, not unbudgeted native ranking; development only"})
        return
    protocol_file = args.output / "protocol.json"
    protocol = json.loads(protocol_file.read_text())
    if protocol["graph_sha256"] != sha(args.graph) or protocol["plans"] != plan_hashes or protocol["questions"] != questions:
        raise ValueError("delivery probe inputs drift")
    for name, expected in protocol["runtime_sha256"].items():
        if sha(runtime / name) != expected:
            raise ValueError("delivery runtime drift")
    from index_free_graph_evidence import Engine
    engine = Engine(args.corpus, args.graph)
    for q in questions:
        plan = plans[q["id"]]
        for arm, options in protocol["arms"].items():
            output = args.output / "responses" / q["id"] / (arm+".json")
            if output.exists():
                continue
            result, diagnostic = engine.query(q["question"], translation=plan["translation"], slots=plan["needs"],
                                      cap=protocol["return_character_cap"], response_mode="evidence", **options)
            save(output, {"question": q, "arm": arm, "result": result, "diagnostic": diagnostic, "public_plan": plan,
                          "protocol_sha256": sha(protocol_file), "guard": guard})
            print("DONE", q["id"], arm, "chars", diagnostic["returned_characters"], flush=True)


if __name__ == "__main__":
    main()
