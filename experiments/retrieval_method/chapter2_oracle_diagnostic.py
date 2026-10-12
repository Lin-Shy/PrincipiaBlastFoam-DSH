"""仅用于隔离的开发诊断：提供完整必要原文后调用固定阿里云8B作答。"""
import argparse
import hashlib
import importlib
import json
from pathlib import Path
import sys


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    if path.exists():
        raise FileExistsError("preserve diagnostic artifact")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=("prepare", "run"))
    p.add_argument("--run", type=Path, required=True)
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
        if out.exists():
            raise FileExistsError("new output required")
        annotations = {a["id"]: a for a in qa.read(arm / "evaluation_only/annotations.json")}
        questions = qa.read(arm / "questions.json")
        rows = []
        hashes = {}
        for q in questions:
            a = annotations[q["family_id"]]
            if q["split"] != "dev" or a["category"] != "cross":
                raise ValueError("only exposed cross development diagnostic permitted")
            sources = []
            for e in a["evidence"]:
                source = arm / "skill/corpus" / e["path"]
                if sha(source) != e["sha256"]:
                    raise ValueError("authoritative source hash mismatch")
                hashes[str(source)] = sha(source)
                lines = source.read_text().splitlines()
                if not 1 <= e["start"] <= e["end"] <= len(lines):
                    raise ValueError("invalid evidence range")
                sources.append({"path": e["path"], "start": e["start"], "end": e["end"],
                                "text": "\n".join(f"{i}: {lines[i-1]}" for i in range(e["start"], e["end"] + 1))})
            messages = [{"role": "system", "content": "只依据提供的带行号权威原文作答。输出JSON；引用精确路径和行段。"},
                        {"role": "user", "content": qa.wire({"question": q["question"], "sources": sources})},
                        {"role": "user", "content": qa.FINAL}]
            rows.append({"question": q, "sources": sources, "request": qa.request(messages, final=True)})
        save(out / "protocol.json", {"schema": "isolated-development-oracle-v1", "role": "development_oracle_answer",
                                     "model": qa.MODEL, "endpoint": qa.ENDPOINT, "rows": rows, "source_sha256": hashes,
                                     "implementation_sha256": sha(Path(__file__)),
                                     "frozen_runtime_sha256": {name: sha(run / name) for name in
                                         ("navigation_qa.py", "chapter2_aliyun_config.py", "graphify_qa.py")},
                                     "retrieval_calls": 0, "annotation_sha256": sha(arm / "evaluation_only/annotations.json"),
                                     "limits": "完整gold原文仅用于开发诊断；一次最终作答，不是正式系统质量或理论上界。"})
        return
    protocol = qa.read(out / "protocol.json")
    if protocol["implementation_sha256"] != sha(Path(__file__)):
        raise ValueError("diagnostic implementation changed")
    for name, expected in protocol["frozen_runtime_sha256"].items():
        if sha(run / name) != expected:
            raise ValueError("runtime drift")
    for source, expected in protocol["source_sha256"].items():
        if sha(Path(source)) != expected:
            raise ValueError("source drift")
    transport.SECRET = config.read_settings(args.settings_file)
    transport.reset_transport_circuit()
    for row in protocol["rows"]:
        folder = out / row["question"]["id"]
        if (folder / "answer.json").exists():
            continue
        response = transport.fetch(folder, "final", row["request"], transport.SECRET)
        selected = qa.choice(response)
        parsed = qa.decode_json_prefix(selected["message"]["content"])
        save(folder / "answer.json", {"question_id": row["question"]["id"], "answer": parsed,
                                      "finish_reason": selected.get("finish_reason"), "model": protocol["model"],
                                      "protocol_sha256": sha(out / "protocol.json")})
        print("DONE", row["question"]["id"], flush=True)


if __name__ == "__main__":
    main()
