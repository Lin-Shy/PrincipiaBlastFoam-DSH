"""第1轮公开开发问句送达诊断；不是公共规划器下的正式原生排名榜。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys

from chapter2_production_guard import install


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    if path.exists():
        raise FileExistsError("preserve development probe artifact")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+"\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "run"))
    parser.add_argument("--questions", type=Path, required=True)
    parser.add_argument("--question-id", action="append", required=True)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--graph", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if os.environ.get("PYTHONHASHSEED") != "0":
        raise ValueError("frozen runtime requires PYTHONHASHSEED=0")
    guard = install(offline=True)
    questions = json.loads(args.questions.read_text())
    if any(q["split"] != "dev" for q in questions):
        raise ValueError("development only")
    selected = [q for q in questions if q["id"] in args.question_id]
    if {q["id"] for q in selected} != set(args.question_id):
        raise ValueError("unknown development question")
    runtime = Path(__file__).parent
    source_files = (Path(__file__).name, "chapter2_production_guard.py", "index_free_graph_evidence.py", "candidate_graph_utils.py", "candidate_paths.py")
    if args.command == "prepare":
        if args.output.exists():
            raise FileExistsError("new probe version required")
        save(args.output / "protocol.json", {"schema": "development-public-question-delivery-probe-v1", "major_round": 1,
             "graph_sha256": sha(args.graph), "public_questions_sha256": sha(args.questions), "questions": selected,
             "source_sha256": {n: sha(runtime / n) for n in source_files}, "python_hash_seed": "0", "guard": guard,
             "arms": {"full": {"with_cross": True}, "no_cross": {"with_cross": False}}, "return_character_cap": 24000,
             "model_calls": 0, "query_policy": "identical raw public question; no translation or fitted needs; response_mode=evidence",
             "limits": "旧query接口按预算选择组；只评价此原文送达，不伪称未经预算裁剪的原生排名或正式质量。无新测试输入。"})
        return
    protocol = json.loads((args.output / "protocol.json").read_text())
    if protocol["graph_sha256"] != sha(args.graph) or protocol["public_questions_sha256"] != sha(args.questions) or protocol["questions"] != selected:
        raise ValueError("probe input drift")
    for name, expected in protocol["source_sha256"].items():
        if sha(runtime / name) != expected:
            raise ValueError("probe runtime drift")
    from index_free_graph_evidence import Engine
    engine = Engine(args.corpus, args.graph)
    for question in selected:
        for arm, options in protocol["arms"].items():
            file = args.output / "responses" / question["id"] / (arm + ".json")
            if file.exists():
                continue
            result, diagnostic = engine.query(question["question"], cap=protocol["return_character_cap"], response_mode="evidence", **options)
            save(file, {"question": question, "arm": arm, "result": result, "diagnostic": diagnostic,
                        "protocol_sha256": sha(args.output / "protocol.json"), "guard": guard})
            print("DONE", question["id"], arm, "groups", len(result["groups"]), "chars", diagnostic["returned_characters"], flush=True)


if __name__ == "__main__":
    main()
