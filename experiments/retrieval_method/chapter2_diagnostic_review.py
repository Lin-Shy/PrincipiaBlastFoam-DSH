"""开发诊断方法盲化复核；评分固定阿里云8B，结构无效单列。"""
import argparse
import hashlib
import importlib
import json
from pathlib import Path
import random
import sys


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    if path.exists():
        raise FileExistsError("immutable review artifact")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


INSTRUCTION = """你是来源核验审阅者。材料已经隐藏方法；只评分回答中的实际内容，不能把gold替回答补全。
逐个gold_points判断correct（事实正确）、complete（全部细节完整）、supported（回答自己的引用是否真正支持该要点）。
仅使用seen_lines；任何引用必须确实见过，且语义支持完整主张。额外错误、过度泛化和默认/实例混淆必须指出。
输出JSON: {points:[{index:从0开始整数,correct:布尔,complete:布尔,supported:布尔,reason:简短中文}],
citations:[{index:从0开始整数,supported:布尔,reason:简短中文}],extra_errors:[字符串]}。
points和citations分别逐项恰好出现一次；不能漏项。supported不因坐标有效而自动为真。"""


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=("prepare", "run"))
    p.add_argument("--run", type=Path, required=True)
    p.add_argument("--oracle", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--settings-file", type=Path)
    args = p.parse_args()
    run, out = args.run.resolve(), args.output.resolve()
    sys.path.insert(0, str(run))
    qa = importlib.import_module("navigation_qa")
    config = importlib.import_module("chapter2_aliyun_config")
    transport = importlib.import_module("graphify_qa")
    config.configure_qa(qa)
    arm = run / "principia_index_free"
    if args.command == "prepare":
        annotations = {a["id"]: a for a in qa.read(arm / "evaluation_only/annotations.json")}
        oracle = qa.read(args.oracle / "protocol.json")
        entries = []
        for row in oracle["rows"]:
            q = row["question"]
            session = arm / "sessions" / (q["id"] + "--graph_first--r1/result.json")
            result = qa.read(session)
            ofile = args.oracle / q["id"] / "answer.json"
            seen = {}
            for source in row["sources"]:
                lines = (arm / "skill/corpus" / source["path"]).read_text().splitlines()
                seen.setdefault(source["path"], {}).update({str(i): lines[i-1] for i in range(source["start"], source["end"] + 1)})
            for mode, answer, sources, origin in (
                    ("retrieval", result["parsed_answer"], result["seen_lines"], session),
                    ("oracle", qa.read(ofile)["answer"], seen, ofile)):
                entries.append({"identity": {"mode": mode, "id": q["id"], "origin": str(origin), "origin_sha256": sha(origin)},
                                "packet": {"question": q["question"], "gold_points": annotations[q["family_id"]]["gold"],
                                           "answer": answer, "seen_lines": sources}})
        random.Random(20261003).shuffle(entries)
        identity = {}
        for i, entry in enumerate(entries):
            key = f"D{i+1:03d}"
            identity[key] = entry["identity"]
            write(out / "packets" / (key + ".json"), entry["packet"])
        write(out / "evaluation_only/identity.json", identity)
        write(out / "protocol.json", {"schema": "development-blind-review-v1", "instruction": INSTRUCTION,
                                      "model": qa.MODEL, "endpoint": qa.ENDPOINT, "role": "diagnostic_review",
                                      "seed": 20261003, "implementation_sha256": sha(Path(__file__)),
                                      "packets": {k: sha(out / "packets" / (k + ".json")) for k in identity},
                                      "limits": "同8B模型自评，仅开发诊断；不是人工复核或正式质量主榜。无结构修复、无答案重采样。"})
        return
    protocol = qa.read(out / "protocol.json")
    if protocol["implementation_sha256"] != sha(Path(__file__)):
        raise ValueError("review implementation drift")
    transport.SECRET = config.read_settings(args.settings_file)
    transport.reset_transport_circuit()
    for key, expected in protocol["packets"].items():
        file = out / "packets" / (key + ".json")
        if sha(file) != expected:
            raise ValueError("review packet drift")
        target = out / "reviews" / key
        if (target / "compiled.json").exists():
            continue
        packet = qa.read(file)
        body = qa.request([{"role": "system", "content": protocol["instruction"]},
                           {"role": "user", "content": qa.wire(packet)}], final=True)
        response = transport.fetch(target, "review", body, transport.SECRET)
        selected = qa.choice(response)
        try:
            review = qa.decode_json_prefix(selected["message"]["content"])
            for collection, count, booleans in (("points", len(packet["gold_points"]), ("correct", "complete", "supported")),
                                                ("citations", len(packet["answer"].get("references", [])), ("supported",))):
                items = review[collection]
                if len(items) != count or sorted(x["index"] for x in items) != list(range(count)):
                    raise ValueError("review index coverage invalid")
                if any(type(x.get(k)) is not bool for x in items for k in booleans):
                    raise ValueError("review booleans invalid")
            if not isinstance(review["extra_errors"], list):
                raise ValueError("invalid extra_errors")
            compiled = {"status": "valid", "review": review,
                        "strict_success": all(x["correct"] and x["complete"] and x["supported"] for x in review["points"])
                            and all(x["supported"] for x in review["citations"]) and not review["extra_errors"]}
        except (ValueError, KeyError, TypeError) as error:
            compiled = {"status": "invalid_structure", "error": type(error).__name__, "strict_success": None}
        write(target / "compiled.json", {**compiled, "packet_sha256": expected, "response_sha256": sha(target / "review.json")})
        print("DONE", key, compiled["status"], flush=True)


if __name__ == "__main__":
    main()
