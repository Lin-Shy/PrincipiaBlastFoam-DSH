"""方法盲化的独立开发评分；实际回答摘录与逐点引用支持须可追溯。"""
import argparse
import hashlib
import importlib
import json
from pathlib import Path
import random
import shutil

INSTRUCTION = """你是方法盲化的blastFoam回答审阅者，只按实际回答及它自己的引用评分。gold_points是评分标准，不能替回答补写或推断。
输入gold_points与references均有明确index；只按既有index逐项填写，不新增、拆分或合并评分点。每个point仅评价它自己的requirement，不将其他point的要求混入；gold未要求的参数、公式、运行信息不能自行增加。
中文忠实解释、等价公式写法和正确的语义概括都可满足requirement；不要求逐字匹配gold的英文，不把保存于gold的作者说明当成需要逐字出现在回答的固定短语。满足全部语义要求时应标complete=true；不能因为措辞不同或没有逐字复制gold就判false。
逐条评分gold_points中所要求的所有细节（所有参数数值/开关/对象、公式和原文变量、用途/条件、命令等）。point.correct表示已回答部分事实正确；complete表示该标准全部细节在实际answer_text中直接表达；supported表示回答自己的引用完整支持该标准。引用的坐标有效不代表语义支持。
对每个point写actual_answer_quote：从answer_text原样摘取包含对应实际答案的文字，未回答填空字符串；不能摘取gold_points或只摘取引用路径。reference_indices仅填真正支持该实际答案的references索引。
逐条references检查它的claim和所附原文quote是否匹配，尤其字典对象、案例、模型角色、默认与显式配置区别、适用条件。原文只支持静态声明，不能证明执行或物理条件满足。指出extra_errors。
输出精确JSON结构：{"points":[{"index":0,"correct":true,"complete":false,"supported":false,"actual_answer_quote":"实际正文摘录","reference_indices":[0],"reason":"理由"}],"citations":[{"index":0,"supported":true,"reason":"理由"}],"extra_errors":[]}。
points和citations必须按输入长度各恰好逐项出现一次，布尔值只能true/false。reason非空，extra_errors为字符串数组。未回答或缺必要细节不能标complete=true，正文未直接说出的参数值不能凭引用补全。"""


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path,value):
    if path.exists():
        raise FileExistsError("new isolated review artifact required")
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n")


def validate(review,packet):
    for name,count,flags in (("points",len(packet["gold_points"]),("correct","complete","supported")),
                             ("citations",len(packet["references"]),("supported",))):
        items=review[name]
        if not isinstance(items,list) or len(items)!=count or any(type(x.get("index")) is not int for x in items) or sorted(x["index"] for x in items)!=list(range(count)):
            raise ValueError("review index coverage")
        if any(type(x.get(k)) is not bool for x in items for k in flags):
            raise ValueError("review boolean type")
        if any(not isinstance(x.get("reason"),str) or not x["reason"].strip() for x in items):
            raise ValueError("review reason missing")
    for point in review["points"]:
        quote=point["actual_answer_quote"]
        refs=point["reference_indices"]
        if not isinstance(quote,str) or quote and quote not in packet["answer_text"]:
            raise ValueError("review invented actual answer quote")
        if not isinstance(refs,list) or len(set(refs))!=len(refs) or any(type(i) is not int or not 0<=i<len(packet["references"]) for i in refs):
            raise ValueError("review reference trace invalid")
        if point["complete"] and not quote.strip() or point["supported"] and not refs:
            raise ValueError("positive point has no actual answer/source trace")
    if not isinstance(review["extra_errors"],list) or any(not isinstance(x,str) for x in review["extra_errors"]):
        raise ValueError("review extra errors type")
    return review


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("command",choices=("prepare","run"))
    for name in ("answers","annotations","output"):
        p.add_argument("--"+name,type=Path,required=True)
    p.add_argument("--settings-file",type=Path)
    args=p.parse_args()
    runtime=Path(__file__).parent
    names=(Path(__file__).name,"chapter2_aliyun_config.py","navigation_qa.py","graphify_qa.py","graphify_query_backend.py")
    if args.command=="prepare":
        if args.output.exists():
            raise FileExistsError("new review version required")
        if not (args.answers/"completion.json").exists():
            raise ValueError("complete answers before blind review")
        annotations=json.loads(args.annotations.read_text())
        if any(a["split"]!="dev" for a in annotations):
            raise ValueError("development annotations only")
        annotations={a["id"]:a for a in annotations}
        answer_protocol_file=args.answers/"protocol.json"
        protocol=json.loads(answer_protocol_file.read_text())
        entries=[]
        for key,expected in protocol["packets"].items():
            packet_file=args.answers/"packets"/(key+".json")
            answer_file=args.answers/"responses"/key/"compiled.json"
            if sha(packet_file)!=expected:
                raise ValueError("answer packet drift")
            packet=json.loads(packet_file.read_text())
            answer=json.loads(answer_file.read_text())
            if answer["packet_sha256"]!=expected or answer["protocol_sha256"]!=sha(answer_protocol_file):
                raise ValueError("answer provenance drift")
            sources={u["citation_id"]:u for u in packet["delivery"]["units"] if u.get("mapping_status") != "unmappable"}
            references=[]
            if answer["status"]=="complete_structure":
                for claim in answer["answer"]["claims"]:
                    for cite in claim["citations"]:
                        unit=sources[cite["source"]]
                        a,b=cite["start"],cite["end"]
                        references.append({"index":len(references),"claim":claim["text"],"path":unit["path"],"start":a,"end":b,
                            "source_sha256":unit["source_sha256"],"quote":"\n".join(unit["lines"][a-unit["start"]:b-unit["start"]+1])})
                actual=answer["answer_text"]
            else:
                raw=json.loads((answer_file.parent/"final.json").read_text())["raw_response"]["choices"][0]["message"]["content"]
                actual=raw
            annotation=annotations[packet["question"]["family_id"]]
            entries.append({"identity":{"question_id":packet["question"]["id"],"family_id":packet["question"]["family_id"],
                "category":annotation["category"],"arm":packet["arm"],"answer_file":str(answer_file.resolve()),
                "answer_sha256":sha(answer_file),"answer_structure":answer["status"]},
                "packet":{"question":packet["question"]["question"],"gold_points":[{"index":i,"requirement":text} for i,text in enumerate(annotation["gold"])],
                          "answer_text":actual,"references":references}})
        random.Random(20261003).shuffle(entries)
        identity={}
        for i,entry in enumerate(entries,1):
            key=f"R{i:03d}"
            identity[key]=entry["identity"]
            save(args.output/"packets"/(key+".json"),entry["packet"])
        save(args.output/"evaluation_only/identity.json",identity)
        for name in names:
            target=args.output/"runtime"/name
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(runtime/name,target)
        save(args.output/"protocol.json",{"schema":"development-cited-answer-blind-review-v2","major_round":3,
            "role":"development_blind_scoring","model":"qwen3-8b","instruction":INSTRUCTION,
            "generation":{"temperature":0,"enable_thinking":False,"max_tokens":2400,"response_format":{"type":"json_object"}},
            "packets":{key:sha(args.output/"packets"/(key+".json")) for key in identity},
            "runtime_sha256":{name:sha(runtime/name) for name in names},"seed":20261003,
            "annotations_sha256":sha(args.annotations),"answer_protocol_sha256":sha(answer_protocol_file),
            "planned_calls":len(identity),"invalid_structure_policy":"retain null score; no repair or quality resampling",
            "limits":"same8B grader, only development diagnostic; quoted answer/source trace is not semantic verification or real human review"})
        return
    if runtime.resolve()!=(args.output/"runtime").resolve():
        raise ValueError("run frozen review snapshot")
    protocol_file=args.output/"protocol.json"
    protocol=json.loads(protocol_file.read_text())
    for name,expected in protocol["runtime_sha256"].items():
        if sha(runtime/name)!=expected:
            raise ValueError("review runtime drift")
    qa=importlib.import_module("navigation_qa")
    config=importlib.import_module("chapter2_aliyun_config")
    transport=importlib.import_module("graphify_qa")
    config.configure_qa(qa)
    transport.SECRET=config.read_settings(args.settings_file)
    transport.reset_transport_circuit()
    for key,expected in protocol["packets"].items():
        file=args.output/"packets"/(key+".json")
        if sha(file)!=expected:
            raise ValueError("review packet drift")
        folder=args.output/"responses"/key
        if (folder/"compiled.json").exists():
            continue
        packet=json.loads(file.read_text())
        response=transport.fetch(folder,"review",qa.request([{"role":"system","content":protocol["instruction"]},
             {"role":"user","content":qa.wire(packet)}],final=True),transport.SECRET)
        try:
            choice=qa.choice(response)
            if choice["finish_reason"]!="stop":
                raise ValueError("review response truncated")
            review=validate(qa.decode_json_prefix(choice["message"]["content"]),packet)
            success=all(x["correct"] and x["complete"] and x["supported"] for x in review["points"]) and all(x["supported"] for x in review["citations"]) and not review["extra_errors"]
            compiled={"status":"valid_structure","review":review,"model_strict_success":success}
        except (ValueError,KeyError,TypeError) as error:
            compiled={"status":"invalid_structure","error":str(error),"model_strict_success":None}
        save(folder/"compiled.json",{**compiled,"packet_sha256":expected,"response_sha256":sha(folder/"review.json"),"protocol_sha256":sha(protocol_file)})
        print("DONE",key,compiled["status"],flush=True)
    save(args.output/"completion.json",{"status":"complete","calls":protocol["planned_calls"],"protocol_sha256":sha(protocol_file)})


if __name__=="__main__":
    main()
