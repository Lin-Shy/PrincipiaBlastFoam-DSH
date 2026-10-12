"""数据审计侧复核历史事实组合和候选间近重复；不得用于生产检索。"""
import argparse
import hashlib
import importlib
import json
from pathlib import Path
import sys
import re


PROMPT = """仅判断当前这一个新事实组合与列出的旧事实组合是否重复，不评价方法。
historical中H开头是旧族，batch中draft开头是新候选，绝不可把新候选当旧族。材料已按共享来源文件、案例或模型标识筛出可能有关的旧族；其他旧族的筛选依据另行审计。
先明确新问题问的配置字段/对象、模型角色与手册模型定义。对旧gold逐项核对：同一文件、同一参数词、同一物理主题并不等于同一个事实组合。模型不同须比较具体定义，不能把packingLimitModel说成热力学查表，不能把granularPressureModel说成radialModel，也不能把mono说成poly。不以常识假定同义。
完整组合已经在旧gold中被要求，且只是改写或替换案例没有新增必要定义/条件/参数关系，才same_combination；旧gold只要求组件而新组合有新增必要关系/说明时shared_component；其他distinct；依据不足uncertain。
JSON: {decisions:[{id:新候选ID,historical_relation:same_combination/shared_component/distinct/uncertain,historical_ids:[本包H开头的旧ID],historical_quote:非空时必须逐字摘录所列旧gold,new_quote:必须逐字摘录当前evidence的原文（含有关键模型/字段/定义），reason:明确新旧角色、所求事实以及新增或重复之处,candidate_cluster_with:[],cluster_reason:""}]}。
same_combination必须指出当前题要求的全部内容是否已在所列旧gold出现；只证明一个组件相同不能判same_combination。只判断给定的事实组合，不宣称未见语料、未见模型知识或统计意义上的完全独立。
"""


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
                history.append({**{k: row[k] for k in ("category", "gold", "concepts", "cases", "targets", "ambiguity")}, "id": f"H{len(history)+1:03d}", "historical_family": row["id"], "source_paths": sorted({e["path"] for e in row["evidence"]})})
        pool = [{k: f[k] for k in ("id", "category", "case", "field", "role", "value", "definition_cluster", "task_types")} for f in families]
        packets = {}
        screening = {}
        for offset, family in enumerate(families):
            identity = f"family-{offset+1:03d}"
            batch = [{k: family[k] for k in ("id", "category", "case", "field", "role", "value", "questions", "evidence", "ambiguities")}]
            paths = {e["path"] for e in family["evidence"]}
            identifiers = set(re.findall(r"[A-Za-z][A-Za-z0-9_+]+", family["value"] + " " + family["field"]))
            identifiers -= {"see", "authoritative", "configuration", "mechanical", "rubber", "gas", "air", "c4", "products", "reactants", "thermoType", "kineticTheory", "type", "rho", "constant", "thermodynamics", "equationOfState", "transport", "thermo", "initiation", "ddtSchemes", "divSchemes"}
            selected, decisions = [], {}
            for old in history:
                overlap = bool(paths & set(old["source_paths"]))
                case = bool(family["case"] and any(path.startswith("tutorials/" + family["case"] + "/") for path in old["source_paths"]))
                old_text = " ".join(old["gold"] + old["concepts"])
                tokens = sorted(token for token in identifiers if re.search(r"(?<![A-Za-z0-9_])" + re.escape(token) + r"(?![A-Za-z0-9_])", old_text, re.I))
                decisions[old["id"]] = {"shared_source_file": overlap, "shared_case": case, "mentioned_identifiers": tokens, "selected": overlap or case or bool(tokens)}
                if decisions[old["id"]]["selected"]:
                    selected.append(old)
            screening[family["id"]] = decisions
            packet = {"historical": selected, "batch": batch}
            file = args.output / "packets" / (identity + ".json")
            save(file, packet)
            packets[identity] = sha(file)
        save(args.output / "screening.json", screening)
        runtime = args.runtime
        save(args.output / "protocol.json", {"schema": "fact-combination-novelty-review-v3", "model": qa.MODEL, "endpoint": qa.ENDPOINT,
             "role": "dataset_novelty_review", "instruction": PROMPT, "planned_calls": len(packets), "packets": packets,
             "drafts_sha256": sha(args.drafts), "historical_annotations_sha256": input_hashes, "screening_sha256": sha(args.output / "screening.json"),
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
                if not d.get("new_quote") or not any(d["new_quote"] in e["quote"] for family in packet["batch"] if family["id"] == d["id"] for e in family["evidence"]):
                    raise ValueError("missing or nonliteral candidate support")
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
