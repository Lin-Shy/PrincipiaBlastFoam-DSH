"""数据审计侧复核历史事实组合和候选间近重复；不得用于生产检索。"""
import argparse
import hashlib
import importlib
import json
from pathlib import Path
import sys


PROMPT = """你仅复核数据的事实组合近重复，不评估检索方法。historical是当前可恢复的50个旧事实族；batch是本批待判断的新候选及其必要原文。只有historical里的H001—H050才是旧族；draft-开头只属于新候选，绝不可把batch本身当成历史族。
区分完整事实组合重复和只共享组件。改变问法、案例但仍只问同一概念与同一取值/定义，不能当独立新事实。只是共享字段、文件或某个旧答案组件，新增必要定义、参数、作用域或多文件关系时可以是新组合，但必须披露shared_component。仅判断每个新族与historical旧族是否同一任务或同义定义。
不得由原文曾被送达推断同任务已测试，不得因不同手册行号就自动判独立；不要以模型知识补充语料。记录可恢复材料限制，uncertain不能自动改为distinct。
JSON输出 {decisions:[{id:本批候选ID, historical_relation:same_combination/shared_component/distinct/uncertain, historical_ids:[只能选H001—H050中的ID], historical_quote:若给出旧ID须逐字摘录相应旧gold中的一段, reason:理由, candidate_cluster_with:固定空数组, cluster_reason:固定空字符串}]}。每个本批候选只出现一次。相同主题并不自动是同一事实族；说明何处构成独立组合或重复。"""


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    if path.exists():
        raise FileExistsError("new audit version required")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "run"))
    parser.add_argument("--drafts", type=Path, required=True)
    parser.add_argument("--historical-dataset", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--settings-file", type=Path)
    args = parser.parse_args()
    sys.path.insert(0, str(args.runtime.resolve()))
    qa = importlib.import_module("navigation_qa")
    config = importlib.import_module("chapter2_aliyun_config")
    transport = importlib.import_module("graphify_qa")
    config.configure_qa(qa)
    if args.command == "prepare":
        families = qa.read(args.drafts)["families"]
        history, input_hashes = [], {}
        for split in ("dev", "holdout"):
            path = args.historical_dataset / (split + ".annotations.json")
            input_hashes[path.name] = sha(path)
            for row in qa.read(path):
                history.append({**{k: row[k] for k in ("category", "gold", "concepts", "cases", "targets", "ambiguity")}, "id": f"H{len(history)+1:03d}", "historical_family": row["id"]})
        pool = [{k: f[k] for k in ("id", "category", "case", "field", "role", "value", "definition_cluster", "task_types")} for f in families]
        packets = {}
        for offset in range(0, len(families), 6):
            identity = f"batch-{offset // 6 + 1:03d}"
            batch = [{k: f[k] for k in ("id", "questions", "evidence", "ambiguities")} for f in families[offset:offset+6]]
            packet = {"historical": history, "batch": batch}
            file = args.output / "packets" / (identity + ".json")
            save(file, packet)
            packets[identity] = sha(file)
        runtime = args.runtime
        save(args.output / "protocol.json", {"schema": "fact-combination-novelty-review-v2", "model": qa.MODEL, "endpoint": qa.ENDPOINT,
             "role": "dataset_novelty_review", "instruction": PROMPT, "planned_calls": len(packets), "packets": packets,
             "drafts_sha256": sha(args.drafts), "historical_annotations_sha256": input_hashes,
             "implementation_sha256": sha(Path(__file__)), "runtime_sha256": {n: sha(runtime / n) for n in ("navigation_qa.py", "graphify_qa.py", "chapter2_aliyun_config.py")},
             "generation": {"temperature": 0, "enable_thinking": False, "max_tokens": 2400},
             "retry_policy": "transport only; invalid structure retained, no quality resampling",
             "limits": "同一8B审查是辅助判断；只覆盖当前50族可恢复标注，不证明从未见过语料。"})
        return
    protocol = qa.read(args.output / "protocol.json")
    if sha(Path(__file__)) != protocol["implementation_sha256"] or sha(args.drafts) != protocol["drafts_sha256"]:
        raise ValueError("audit input or implementation drift")
    for name, expected in protocol["runtime_sha256"].items():
        if sha(args.runtime / name) != expected:
            raise ValueError("runtime drift")
    for name, expected in protocol["historical_annotations_sha256"].items():
        if sha(args.historical_dataset / name) != expected:
            raise ValueError("historical input drift")
    transport.SECRET = config.read_settings(args.settings_file)
    transport.reset_transport_circuit()
    for identity, expected in protocol["packets"].items():
        packet_file = args.output / "packets" / (identity + ".json")
        if sha(packet_file) != expected:
            raise ValueError("packet drift")
        folder = args.output / "responses" / identity
        if (folder / "compiled.json").exists():
            continue
        packet = qa.read(packet_file)
        body = qa.request([{"role": "system", "content": protocol["instruction"]}, {"role": "user", "content": qa.wire(packet)}], final=True)
        response = transport.fetch(folder, "review", body, transport.SECRET)
        try:
            review = qa.decode_json_prefix(qa.choice(response)["message"]["content"])
            decisions = review["decisions"]
            batch_ids = {f["id"] for f in packet["batch"]}
            pool_ids = set()
            history = {f["id"]: f for f in packet["historical"]}
            if len(decisions) != len(batch_ids) or {d["id"] for d in decisions} != batch_ids:
                raise ValueError("incomplete or duplicate batch judgments")
            for d in decisions:
                if d["historical_relation"] not in {"same_combination", "shared_component", "distinct", "uncertain"} or not d["reason"]:
                    raise ValueError("invalid relation or rationale")
                if not isinstance(d["historical_ids"], list) or any(key not in history for key in d["historical_ids"]):
                    raise ValueError("unknown historical family")
                if d["historical_ids"] and (not d["historical_quote"] or not any(d["historical_quote"] in gold for key in d["historical_ids"] for gold in history[key]["gold"])):
                    raise ValueError("nonliteral historical basis")
                if not isinstance(d["candidate_cluster_with"], list) or any(key not in pool_ids or key == d["id"] for key in d["candidate_cluster_with"]):
                    raise ValueError("invalid candidate cluster")
                if d["candidate_cluster_with"] and not d["cluster_reason"]:
                    raise ValueError("missing cluster rationale")
            result = {"status": "valid", "review": review}
        except (ValueError, TypeError, KeyError) as error:
            result = {"status": "invalid", "error": type(error).__name__}
        save(folder / "compiled.json", {**result, "packet_sha256": expected, "response_sha256": sha(folder / "review.json")})
        print("DONE", identity, result["status"], flush=True)


if __name__ == "__main__":
    main()
