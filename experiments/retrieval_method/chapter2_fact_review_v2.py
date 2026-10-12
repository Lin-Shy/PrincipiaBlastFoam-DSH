"""阿里云8B复核扩充数据草案；不执行检索、问答或方法开发。"""
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
        raise FileExistsError("preserve dataset review artifact")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


PROMPT = """仅审查数据草案的事实依据与公开问法，不调用检索，不评价任何方法。
本轮含单来源、实际参数、单位/公式、默认值/原文歧义及多文件任务，逐项核对所问细节确有来源。
source中配置声明不证明运行条件满足。单来源题只要求其自身来源类型的支持。
教程配置只是声明；不得据此推断物理运行条件已经满足。核对声明字段的角色、对象和作用域是否与手册模型相符。
若同名模型属于不同角色（例如黏度与导热、界面压力与边界条件），应判role_alignment=false。
三问必须各自独立可理解、指定案例和字段对象，且要求同一事实组合；不以更多问法增加统计独立样本。
首段用途说明对应的手册节标题也是证据。评估sources是否足以支持草案，不得用常识或gold标签补缺。
输出JSON: {role_alignment:布尔,factual_support:布尔,scope_unambiguous:布尔,
questions:[{index:0到2,self_contained:布尔,same_task:布尔,reason:简短理由}],
quotes:[{path:原始路径,text:必须为sources内可找到的非空原文摘录；仅允许空白归一，不改词或符号}],issues:[字符串]}。
若role_alignment和factual_support均为true，quotes必须覆盖本题evidence中全部来源类型；单来源题只要求自身来源。
不要将sources未声明的物理条件视为成立；发现教程选择与手册适用范围冲突可记录issues，但事实题只要求分别报告声明与定义。"""


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=("prepare", "run"))
    p.add_argument("--drafts", type=Path, required=True)
    p.add_argument("--corpus", type=Path, required=True)
    p.add_argument("--runtime", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--settings-file", type=Path)
    args = p.parse_args()
    out, runtime = args.output.resolve(), args.runtime.resolve()
    sys.path.insert(0, str(runtime))
    qa = importlib.import_module("navigation_qa")
    config = importlib.import_module("chapter2_aliyun_config")
    transport = importlib.import_module("graphify_qa")
    config.configure_qa(qa)
    if args.command == "prepare":
        drafts = qa.read(args.drafts)
        packets = {}
        for family in drafts["families"]:
            sources = []
            for atom in family["evidence"]:
                file = args.corpus / atom["path"]
                if sha(file) != atom["sha256"]:
                    raise ValueError("source drift")
                lines = file.read_text().splitlines()
                if "\n".join(lines[atom["start"]-1:atom["end"]]) != atom["quote"]:
                    raise ValueError("evidence quote mismatch")
                # 全配置文件用于对象/字典作用域复核；不是生产检索上下文。
                start, end = (1, len(lines)) if atom["source_kind"] == "tutorial" else (atom["start"], atom["end"])
                sources.append({"path": atom["path"], "start": start, "end": end,
                                "text": "\n".join(lines[start-1:end]), "sha256": atom["sha256"]})
            packet = {"id": family["id"], "questions": family["questions"], "case": family["case"],
                      "field": family["field"], "role": family["role"], "declared_value": family["value"], "sources": sources,
                      "category": family["category"], "evidence": family["evidence"],
                      "task_types": family["task_types"], "ambiguities": family["ambiguities"]}
            save(out / "packets" / (family["id"] + ".json"), packet)
            packets[family["id"]] = sha(out / "packets" / (family["id"] + ".json"))
        save(out / "protocol.json", {"schema": "expanded-fact-question-review-v2", "model": qa.MODEL, "endpoint": qa.ENDPOINT,
                                     "role": "dataset_fact_question_review", "instruction": PROMPT,
                                     "drafts_sha256": sha(args.drafts), "packets": packets, "planned_calls": len(packets),
                                     "implementation_sha256": sha(Path(__file__)), "split_assigned": False,
                                     "retry_policy": "identical transport only; invalid structure retained without repair",
                                     "generation": {"temperature": 0, "enable_thinking": False, "max_tokens": 2400},
                                     "runtime_sha256": {n: sha(runtime / n) for n in ("navigation_qa.py", "chapter2_aliyun_config.py", "graphify_qa.py")}})
        return
    protocol = qa.read(out / "protocol.json")
    if sha(Path(__file__)) != protocol["implementation_sha256"] or sha(args.drafts) != protocol["drafts_sha256"]:
        raise ValueError("review implementation or drafts drift")
    for name, expected in protocol["runtime_sha256"].items():
        if sha(runtime / name) != expected:
            raise ValueError("runtime drift")
    transport.SECRET = config.read_settings(args.settings_file)
    transport.reset_transport_circuit()
    for key, expected in protocol["packets"].items():
        packet_file = out / "packets" / (key + ".json")
        if sha(packet_file) != expected:
            raise ValueError("packet drift")
        folder = out / "responses" / key
        if (folder / "compiled.json").exists():
            continue
        packet = qa.read(packet_file)
        body = qa.request([{"role": "system", "content": protocol["instruction"]},
                           {"role": "user", "content": qa.wire(packet)}], final=True)
        response = transport.fetch(folder, "review", body, transport.SECRET)
        choice = qa.choice(response)
        try:
            parsed = qa.decode_json_prefix(choice["message"]["content"])
            if any(type(parsed.get(k)) is not bool for k in ("role_alignment", "factual_support", "scope_unambiguous")):
                raise ValueError("invalid family booleans")
            q = parsed["questions"]
            if len(q) != 3 or sorted(x["index"] for x in q) != [0, 1, 2] or any(type(x.get(k)) is not bool for x in q for k in ("self_contained", "same_task")):
                raise ValueError("invalid question decisions")
            sources = {x["path"]: x["text"] for x in packet["sources"]}
            quotes = parsed["quotes"]
            if not isinstance(quotes, list) or any(not x.get("text") or x.get("path") not in sources or " ".join(x["text"].split()) not in " ".join(sources[x["path"]].split()) for x in quotes):
                raise ValueError("nonliteral tokens or unavailable support quote")
            if parsed["role_alignment"] and parsed["factual_support"] and {x["path"].split("/")[0] for x in quotes} != {x["path"].split("/")[0] for x in packet["evidence"]}:
                raise ValueError("missing two-source support quotes")
            result = {"status": "valid", "review": parsed, "candidate_accepted": all(parsed[k] for k in
                      ("role_alignment", "factual_support", "scope_unambiguous")) and all(x["self_contained"] and x["same_task"] for x in q)}
        except (KeyError, ValueError, TypeError) as error:
            result = {"status": "invalid_structure_or_quote", "error": type(error).__name__, "candidate_accepted": None}
        save(folder / "compiled.json", {**result, "packet_sha256": expected, "response_sha256": sha(folder / "review.json")})
        print("DONE", key, result["status"], result["candidate_accepted"], flush=True)


if __name__ == "__main__":
    main()
