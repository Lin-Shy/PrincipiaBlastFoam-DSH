"""独立开发评分进程核对原文送达；不生成检索规则，也不评分测试集。"""
import argparse
import hashlib
import json
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ("probe", "annotations", "corpus", "output"):
        p.add_argument("--"+name, type=Path, required=True)
    args = p.parse_args()
    if args.output.exists():
        raise FileExistsError("new isolated development scoring version required")
    annotations = json.loads(args.annotations.read_text())
    if any(a["split"] != "dev" for a in annotations):
        raise ValueError("development annotations only")
    gold = {a["id"]: a for a in annotations}
    protocol_file = args.probe / "protocol.json"
    protocol = json.loads(protocol_file.read_text())
    rows, source_lines = [], {}
    for q in protocol["questions"]:
        for arm in protocol["arms"]:
            file = args.probe / "responses" / q["id"] / (arm+".json")
            if not file.exists():
                rows.append({"id": q["id"], "arm": arm, "status": "missing"})
                continue
            packet = json.loads(file.read_text())
            if packet["protocol_sha256"] != sha(protocol_file) or packet["question"] != q:
                raise ValueError("probe input drift")
            result, delivered = packet["result"], {}
            verified_lines = 0
            for unit in result["evidence"].values():
                path = result["sources"][unit["source"]]
                if path not in source_lines:
                    source_lines[path] = (args.corpus / path).read_text().splitlines()
                original = source_lines[path]
                start, end = unit["start"], unit["end"]
                if not 1 <= start <= end <= len(original):
                    raise ValueError("delivered range outside original source")
                text = "\n".join(f"{i}: {original[i-1]}" for i in range(start, end+1))
                if unit["text"] != text:
                    raise ValueError("delivered source text drift")
                delivered.setdefault(path, set()).update(range(start, end+1))
                verified_lines += end-start+1
            atoms = []
            for atom in gold[q["family_id"]]["evidence"]:
                if sha(args.corpus / atom["path"]) != atom["sha256"]:
                    raise ValueError("development gold source drift")
                needed = set(range(atom["start"], atom["end"]+1))
                seen = delivered.get(atom["path"], set())
                atoms.append({"id": atom["id"], "path": atom["path"], "start": atom["start"], "end": atom["end"],
                              "complete": needed <= seen, "overlap_fraction": len(needed & seen)/len(needed)})
            rows.append({"id": q["id"], "family_id": q["family_id"], "arm": arm, "status": "verified",
                         "response_sha256": sha(file), "returned_characters": packet["diagnostic"]["returned_characters"],
                         "query_seconds": packet["diagnostic"]["seconds"], "groups": len(result["groups"]),
                         "source_lines_checked_with_duplicates": verified_lines,
                         "complete_atoms": sum(a["complete"] for a in atoms), "necessary_atoms": len(atoms),
                         "complete_evidence_set": all(a["complete"] for a in atoms), "atoms": atoms})
    out = {"schema": "isolated-development-delivered-source-score-v1", "probe_protocol_sha256": sha(protocol_file),
           "annotations_sha256": sha(args.annotations), "implementation_sha256": sha(Path(__file__)), "rows": rows,
           "model_calls": 0, "limits": "3个预定开发原文查询、同24k字符cap、无公共LLM规划；只核对已送达原文，非正式原生排名榜或答案质量。不据此扩大样本或推断正式优势。"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(out, ensure_ascii=False, indent=2)+"\n")
    print(json.dumps([{k: r[k] for k in ("id", "arm", "status", "complete_atoms", "necessary_atoms", "complete_evidence_set", "query_seconds")} for r in rows], ensure_ascii=False))


if __name__ == "__main__":
    main()
