"""隔离的开发评分侧必要配置标识缺项检查，不调用模型、不供检索导入。"""
import argparse
import hashlib
import json
from pathlib import Path
import re


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--blind-review", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        raise FileExistsError("new isolated audit version required")
    # 旧开发题必须明确报告的技术配置名称；不是穷尽答案质量评分器。
    obligations = {"Q014-n1": ["tabulatedMG", "const"], "Q027-n1": ["vanLeerV", "RK4SSP"],
                   "Q030-n1": ["impulse", "dynamicP"]}
    identity_file = args.blind_review / "evaluation_only/identity.json"
    identity = json.loads(identity_file.read_text())
    protocol_file = args.blind_review / "protocol.json"
    protocol = json.loads(protocol_file.read_text())
    rows = []
    for key, meta in identity.items():
        packet_file = args.blind_review / "packets" / (key + ".json")
        if sha(packet_file) != protocol["packets"][key] or sha(Path(meta["origin"])) != meta["origin_sha256"]:
            raise ValueError("diagnostic input drift")
        packet = json.loads(packet_file.read_text())
        text = packet["answer"]["answer"]
        gold = " ".join(packet["gold_points"])
        checks = []
        for name in obligations[meta["id"]]:
            pattern = r"(?<![A-Za-z0-9_])" + re.escape(name) + r"(?![A-Za-z0-9_])"
            if re.search(pattern, gold) is None:
                raise ValueError("missing literal is not an applicable old gold obligation")
            checks.append({"required_configuration_identifier": name, "present_in_actual_answer_text": re.search(pattern, text) is not None})
        missing = [c["required_configuration_identifier"] for c in checks if not c["present_in_actual_answer_text"]]
        rows.append({"blind_id": key, "mode": meta["mode"], "question_id": meta["id"], "packet_sha256": sha(packet_file),
                     "checks": checks, "missing_identifiers": missing, "definite_requested_configuration_omission": bool(missing),
                     "answer_text": text, "strict_semantic_score": None})
    out = {"schema": "development-necessary-literal-omission-audit-v1", "implementation_sha256": sha(Path(__file__)),
           "blind_protocol_sha256": sha(protocol_file), "identity_sha256": sha(identity_file), "rows": rows,
           "retrieval_answers_with_definite_omission": sum(r["mode"] == "retrieval" and r["definite_requested_configuration_omission"] for r in rows),
           "oracle_answers_with_definite_omission": sum(r["mode"] == "oracle" and r["definite_requested_configuration_omission"] for r in rows),
           "limits": "只是明确要求的技术模型/字段标识缺项：引用或gold不能替回答正文补写。未缺项不代表正确完整，不按本检查恢复旧模型评分；不构成能力理论上界。oracle固定单次FINAL与多步工作流不同。"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(out, ensure_ascii=False, indent=2)+"\n")
    print(json.dumps({"retrieval_definite_omissions": out["retrieval_answers_with_definite_omission"],
                      "oracle_definite_omissions": out["oracle_answers_with_definite_omission"], "model_calls": 0}))


if __name__ == "__main__":
    main()
