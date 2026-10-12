"""逐要求评分与整体引用审计；避免8B自行拆分评分数组或复制示例布尔值。"""
import argparse
import hashlib
import importlib
import json
from pathlib import Path
import shutil

POINT = """只评价输入的单个requirement，不自行增加或拆分评分要求。gold是语义标准，不能替实际回答补写；忠实中文、等价公式、等价概括都允许，不要求逐字复制gold的英文或作者说明。
根据actual_answer_quote（从answer_text原样摘取，未回答则空字符串）判断assessment：satisfied=本要求所有事实细节都直接回答且正确；partial=已回答部分正确但缺明确所要求细节；missing=没有回答本要求；incorrect=所回答内容有实质错误。不能因措辞不同或未回答本要求以外的参数而判partial。
support只评价该实际答案自己的引用：supported=references中引文完整支持该答案及必要对象/角色；partial=只支持部分；unsupported=没有支持。reference_indices只写真实支持该答案的输入reference.index。不能把引用坐标合法当语义支持，不能用gold或模型记忆支持答案。
输出一个JSON对象，字段为assessment（只能satisfied/partial/missing/incorrect之一）、support（只能supported/partial/unsupported之一）、actual_answer_quote（字符串）、reference_indices（整数数组）、reason（非空中文字符串）。没有默认标签；不得输出评分数组、index或其他字段。"""
CITATIONS = """独立核验actual answer的全部references及额外事实错误，不增添问题/gold未要求的任务。对每个reference，claim是否真的由它自己的quote支持，包括对象、角色、条件和参数？正文忠实概括和等价公式允许，不能要求逐字复制原文。
整体state：supported表示全部已有引用支持其主张且无额外事实错误；unsupported表示至少一个引用不能支持其主张或有额外事实错误；uncertain表示现有材料无法确定。bad_reference_indices列出不能支持的reference.index，extra_errors列出引用之外的额外事实错误/禁用结论。没有引用不能判断为supported，应填uncertain。
输出一个JSON对象，字段仅为state（supported/unsupported/uncertain之一）、bad_reference_indices（整数数组）、extra_errors（字符串数组）、reason（非空中文字符串）。没有默认标签，不输出每条引用的评分数组。不能用gold为实际回答补全。"""


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path,value):
    if path.exists():
        raise FileExistsError("new immutable review artifact required")
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n")


def validate(value,packet,kind):
    if not isinstance(value,dict) or not isinstance(value.get("reason"),str) or not value["reason"].strip():
        raise ValueError("review object/reason invalid")
    if kind=="point":
        if set(value)!={"assessment","support","actual_answer_quote","reference_indices","reason"}:
            raise ValueError("point schema invalid")
        if value["assessment"] not in {"satisfied","partial","missing","incorrect"} or value["support"] not in {"supported","partial","unsupported"}:
            raise ValueError("point label invalid")
        quote=value["actual_answer_quote"]
        if not isinstance(quote,str) or quote and quote not in packet["answer_text"]:
            raise ValueError("actual answer quote invented")
        indices=value["reference_indices"]
        if value["assessment"]=="satisfied" and not quote.strip() or value["support"]=="supported" and not indices:
            raise ValueError("positive point without actual answer/source trace")
    else:
        if set(value)!={"state","bad_reference_indices","extra_errors","reason"} or value["state"] not in {"supported","unsupported","uncertain"}:
            raise ValueError("citation audit schema/label invalid")
        indices=value["bad_reference_indices"]
        if not isinstance(value["extra_errors"],list) or any(not isinstance(x,str) or not x.strip() for x in value["extra_errors"]):
            raise ValueError("citation extra errors invalid")
        if value["state"]=="supported" and (indices or value["extra_errors"] or not packet["references"]):
            raise ValueError("positive citation audit inconsistent")
        if value["state"]=="unsupported" and not (indices or value["extra_errors"]):
            raise ValueError("negative citation audit has no specific finding")
    if not isinstance(indices,list) or len(set(indices))!=len(indices) or any(type(i) is not int or not 0<=i<len(packet["references"]) for i in indices):
        raise ValueError("reference trace index invalid")
    return value


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("command",choices=("prepare","run"))
    p.add_argument("--blind-review",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--settings-file",type=Path)
    args=p.parse_args()
    runtime=Path(__file__).parent
    names=(Path(__file__).name,"chapter2_aliyun_config.py","navigation_qa.py","graphify_qa.py","graphify_query_backend.py")
    if args.command=="prepare":
        if args.output.exists():
            raise FileExistsError("new pointwise scoring protocol required")
        source_protocol_file=args.blind_review/"protocol.json"
        source_protocol=json.loads(source_protocol_file.read_text())
        jobs={}
        for key,expected in source_protocol["packets"].items():
            file=args.blind_review/"packets"/(key+".json")
            if sha(file)!=expected:
                raise ValueError("blind input drift")
            original=json.loads(file.read_text())
            packet={k:original[k] for k in ("question","answer_text","references")}
            for point in original["gold_points"]:
                job=key+"--p"+str(point["index"])
                save(args.output/"packets"/(job+".json"),{**packet,"requirement":point["requirement"]})
                jobs[job]={"blind_id":key,"kind":"point","point_index":point["index"],"packet_sha256":sha(args.output/"packets"/(job+".json"))}
            job=key+"--citations"
            save(args.output/"packets"/(job+".json"),packet)
            jobs[job]={"blind_id":key,"kind":"citations","packet_sha256":sha(args.output/"packets"/(job+".json"))}
        for name in names:
            target=args.output/"runtime"/name
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(runtime/name,target)
        identity_file=args.blind_review/"evaluation_only/identity.json"
        save(args.output/"evaluation_only/identity.json",json.loads(identity_file.read_text()))
        save(args.output/"protocol.json",{"schema":"development-pointwise-blind-review-v1","major_round":3,
            "model":"qwen3-8b","role":"development_pointwise_scoring","point_instruction":POINT,"citation_instruction":CITATIONS,
            "generation":{"temperature":0,"enable_thinking":False,"max_tokens":700,"response_format":{"type":"json_object"}},
            "source_blind_protocol_sha256":sha(source_protocol_file),"source_identity_sha256":sha(identity_file),
            "jobs":jobs,"planned_calls":len(jobs),"sessions":len(source_protocol["packets"]),
            "runtime_sha256":{name:sha(runtime/name) for name in names},
            "invalid_structure_policy":"retain null labels; no repair or semantic-quality resampling",
            "limits":"last development round evaluator-format correction, unchanged24 frozen answers; same8B limitations and real human audit remain"})
        return
    if runtime.resolve()!=(args.output/"runtime").resolve():
        raise ValueError("run frozen pointwise snapshot")
    protocol_file=args.output/"protocol.json"
    protocol=json.loads(protocol_file.read_text())
    for name,expected in protocol["runtime_sha256"].items():
        if sha(runtime/name)!=expected:
            raise ValueError("pointwise runtime drift")
    qa=importlib.import_module("navigation_qa")
    config=importlib.import_module("chapter2_aliyun_config")
    transport=importlib.import_module("graphify_qa")
    config.configure_qa(qa)
    transport.SECRET=config.read_settings(args.settings_file)
    transport.reset_transport_circuit()
    for key,job in protocol["jobs"].items():
        file=args.output/"packets"/(key+".json")
        if sha(file)!=job["packet_sha256"]:
            raise ValueError("pointwise packet drift")
        folder=args.output/"responses"/key
        if (folder/"compiled.json").exists():
            continue
        packet=json.loads(file.read_text())
        prompt=protocol["point_instruction"] if job["kind"]=="point" else protocol["citation_instruction"]
        response=transport.fetch(folder,"review",qa.request([{"role":"system","content":prompt},
             {"role":"user","content":qa.wire(packet)}],final=False),transport.SECRET)
        try:
            choice=qa.choice(response)
            if choice["finish_reason"]!="stop":
                raise ValueError("pointwise response truncated")
            review=validate(qa.decode_json_prefix(choice["message"]["content"]),packet,job["kind"])
            compiled={"status":"valid_structure","review":review}
        except (ValueError,KeyError,TypeError) as error:
            compiled={"status":"invalid_structure","error":str(error),"review":None}
        save(folder/"compiled.json",{**compiled,"packet_sha256":job["packet_sha256"],"response_sha256":sha(folder/"review.json"),"protocol_sha256":sha(protocol_file)})
        print("DONE",key,compiled["status"],flush=True)
    save(args.output/"completion.json",{"status":"complete","calls":len(protocol["jobs"]),"protocol_sha256":sha(protocol_file)})


if __name__=="__main__":
    main()
