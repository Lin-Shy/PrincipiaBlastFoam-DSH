"""统一两阶段8B带引用回答；只能引用实际送达的权威原文行。"""
import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
import shutil

from chapter2_production_guard import install

DRAFT_PROMPT = """你依据所附blastFoam手册与教程的权威原文回答公开问题。逐项处理题目所有明确要求，包括实际模型选择、每个参数/开关、默认值、首个公式及原文变量、适用条件、多文件命令；只处理问题实际问到的项目。
教程声明和手册定义须分开说明，不能把默认值当实例配置，不能把模型同名当角色相同，不能声称已经运行或运行条件满足。保留命令、公式、单位和尺寸原文；原文不清楚时明确列出缺口。不得依据模型记忆或规划补写事实。
每条claims是最终回答中的一句或一组相关事实，必须在text中直接包含具体答案，并引用支持它的实际送达原文。citation的source使用[S编号]头部中编号（如S1），start/end只写头部后实际出现的原文行号，不得引用requested_lines中未显示的行。
配置引用要包含识别所属字典或对象的必要开头和模型声明，不能仅引用无对象的一行数值；多个相关原文区间可以分开引用。用途和条件可以忠实中文表达，无需逐字复制英文。
仅输出JSON，精确结构例子：{"claims":[{"text":"完整中文事实与必要技术原文","citations":[{"source":"S1","start":1,"end":2}]}],"unresolved":["问题要求但所附原文不能支持的项目"]}。
claims和unresolved均为数组。证据不足时允许claims为空；不要用unresolved代替已有证据可回答的项目。"""
VERIFY_PROMPT = """复核刚才的草稿并生成最终同结构JSON。逐项对照原始问题：模型/字段/所有数值与开关、位置、手册用途/条件、首个公式与明写变量、默认值、多文件命令（仅所问项目）是否都在claims的text中直接回答？补充已有证据支持的遗漏，纠正角色/字典对象/案例混淆、数值和公式抄写错误。
逐条核对引用是否显示了该事实、所需作用域及真实行号；删去不能支持的结论并列入unresolved。教程静态声明不能证明执行成功；手册默认不是实例显式值。引用只来自之前实际送达的[S编号]原文。只输出与草稿相同的claims/unresolved JSON结构，不输出复核意见、评分或隐藏推理。"""


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path,value):
    if path.exists():
        raise FileExistsError("new frozen answer artifact required")
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n")


def validate(value,delivery):
    if not isinstance(value,dict) or set(value)!={"claims","unresolved"}:
        raise ValueError("invalid answer object")
    if not isinstance(value["claims"],list) or len(value["claims"])>40 or not isinstance(value["unresolved"],list) or any(not isinstance(x,str) or not x.strip() for x in value["unresolved"]):
        raise ValueError("invalid claim/unresolved arrays")
    sources={u["citation_id"]:u for u in delivery["units"] if u.get("mapping_status") != "unmappable"}
    for claim in value["claims"]:
        if not isinstance(claim,dict) or set(claim)!={"text","citations"} or not isinstance(claim["text"],str) or not claim["text"].strip():
            raise ValueError("invalid claim")
        if not isinstance(claim["citations"],list) or not claim["citations"]:
            raise ValueError("claim has no citation")
        for cite in claim["citations"]:
            if not isinstance(cite,dict) or set(cite)!={"source","start","end"}:
                raise ValueError("invalid citation object")
            unit=sources.get(cite["source"])
            if not unit or type(cite["start"]) is not int or type(cite["end"]) is not int or not unit["start"]<=cite["start"]<=cite["end"]<=unit["end"]:
                raise ValueError("citation outside delivered authoritative lines")
    if not value["claims"] and not value["unresolved"]:
        raise ValueError("empty answer without disclosure")
    return value


def answer_text(value,delivery):
    sources={u["citation_id"]:u for u in delivery["units"] if u.get("mapping_status") != "unmappable"}
    lines=[]
    for claim in value["claims"]:
        refs=[f"{sources[c['source']]['path']}:{c['start']}-{c['end']}" for c in claim["citations"]]
        lines.append(claim["text"]+" ["+"; ".join(refs)+"]")
    if value["unresolved"]:
        lines.append("证据缺口："+"；".join(value["unresolved"]))
    return "\n".join(lines)


def verification_feedback(draft, delivery, qa):
    try:
        choice = qa.choice(draft)
        if choice["finish_reason"] != "stop":
            raise ValueError("draft response truncated")
        validate(qa.decode_json_prefix(choice["message"]["content"]), delivery)
        feedback = {"coordinate_check": "passed", "limits": "coordinate validity does not prove semantic support or complete answer"}
    except (ValueError, TypeError, KeyError) as error:
        feedback = {"coordinate_check": "failed", "error": str(error)[:250],
                    "action": "correct the draft schema/citations using only original delivered lines; move unsupported facts to unresolved"}
    text = qa.wire(feedback)
    if len(text)+len("程序坐标检查：")>512:
        raise ValueError("reserved feedback character budget exceeded")
    return text


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("command",choices=("prepare","run"))
    for name in ("probe","planner","output"):
        p.add_argument("--"+name,type=Path,required=True)
    p.add_argument("--settings-file",type=Path)
    args=p.parse_args()
    if os.environ.get("PYTHONHASHSEED")!="0":
        raise ValueError("set PYTHONHASHSEED=0")
    guard=install(offline=False)
    probe_file=args.probe/"protocol.json"
    probe=json.loads(probe_file.read_text())
    planner_file=args.planner/"protocol.json"
    planner=json.loads(planner_file.read_text())
    if planner["model"]!="qwen3-8b" or planner["role"]!="common_query_planning_development":
        raise ValueError("fixed8B development planner required")
    questions=[q for q in probe["questions"] if q["id"].endswith("-n1")]
    if len(questions)!=12 or any(q["split"]!="dev" for q in questions):
        raise ValueError("all12 development families fixed first variant")
    packets={}
    for q in questions:
        plan_file=args.planner/"responses"/q["id"]/"compiled.json"
        compiled=json.loads(plan_file.read_text())
        if compiled["question"]!=q or compiled["protocol_sha256"]!=sha(planner_file):
            raise ValueError("common planning drift")
        for arm in ("full","no_cross"):
            file=args.probe/"responses"/q["id"]/(arm+".json")
            packet=json.loads(file.read_text())
            if packet["question"]!=q or packet["protocol_sha256"]!=sha(probe_file):
                raise ValueError("delivered evidence drift")
            from chapter2_canonical_delivery import render
            packets[q["id"]+"--"+arm]={"question":q,"arm":arm,"delivery":render(packet["canonical_units"],23488),
                "retrieval_response_sha256":sha(file),"planner_compiled_sha256":sha(plan_file),
                "planner_status":compiled["status"],"retrieval_query_policy":probe["query_policy"]}
    runtime=Path(__file__).parent
    names=(Path(__file__).name,"chapter2_production_guard.py","chapter2_aliyun_config.py","navigation_qa.py","graphify_qa.py","graphify_query_backend.py","chapter2_canonical_delivery.py","canonical_evidence_v1.py")
    if args.command=="prepare":
        if args.output.exists():
            raise FileExistsError("new answer experiment required")
        for name in names:
            target=args.output/"runtime"/name
            target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(runtime/name,target)
        for key,packet in packets.items():
            save(args.output/"packets"/(key+".json"),packet)
        save(args.output/"protocol.json",{"schema":"development-uniform-cited-answer-v2","major_round":3,
            "model":"qwen3-8b","role":"development_cited_answer","generation":{"temperature":0,"enable_thinking":False,"max_tokens_per_stage":2400,"response_format":{"type":"json_object"}},
            "draft_instruction":DRAFT_PROMPT,"verify_instruction":VERIFY_PROMPT,"guard":guard,
            "probe_protocol_sha256":sha(probe_file),"planner_protocol_sha256":sha(planner_file),
            "packets":{key:sha(args.output/"packets"/(key+".json")) for key in packets},
            "runtime_sha256":{name:sha(runtime/name) for name in names},"planned_sessions":24,"planned_model_calls":48,
            "return_character_cap":24000,"source_character_cap":23488,"feedback_character_reserve":512,"workflow":"one delivered source context, draft, deterministic coordinate check feedback, verification/correction using same conversation; no additional retrieval or quality retries",
            "invalid_structure_policy":"retain raw draft/final; final invalid is incomplete; never replace by gold or resample",
            "transport_retry":"identical request only, retained attempts",
            "limits":"12 development families n1 x2 arms, no formal CI; query policy inherited from selected frozen probe; two-stage answer does not prove semantic quality"})
        return
    if runtime.resolve()!=(args.output/"runtime").resolve():
        raise ValueError("run frozen answer runtime")
    protocol_file=args.output/"protocol.json"
    protocol=json.loads(protocol_file.read_text())
    if protocol["probe_protocol_sha256"]!=sha(probe_file) or protocol["planner_protocol_sha256"]!=sha(planner_file):
        raise ValueError("answer input drift")
    for name,expected in protocol["runtime_sha256"].items():
        if sha(runtime/name)!=expected:
            raise ValueError("answer runtime drift")
    qa=importlib.import_module("navigation_qa")
    config=importlib.import_module("chapter2_aliyun_config")
    transport=importlib.import_module("graphify_qa")
    config.configure_qa(qa)
    transport.SECRET=config.read_settings(args.settings_file)
    transport.reset_transport_circuit()
    for key,expected in protocol["packets"].items():
        packet_file=args.output/"packets"/(key+".json")
        if sha(packet_file)!=expected:
            raise ValueError("answer packet drift")
        packet=json.loads(packet_file.read_text())
        folder=args.output/"responses"/key
        if (folder/"compiled.json").exists():
            existing=json.loads((folder/"compiled.json").read_text())
            if existing["protocol_sha256"]!=sha(protocol_file):
                raise ValueError("existing answer drift")
            continue
        messages=[{"role":"system","content":protocol["draft_instruction"]},
                  {"role":"user","content":"公开问题："+packet["question"]["question"]+"\n权威原文：\n"+packet["delivery"]["text"]}]
        draft=transport.fetch(folder,"draft",qa.request(messages,final=True),transport.SECRET)
        draft_text=qa.choice(draft)["message"]["content"]
        feedback = verification_feedback(draft, packet["delivery"], qa)
        if len(feedback)+len("程序坐标检查：")+packet["delivery"]["returned_characters"]>protocol["return_character_cap"]:
            raise ValueError("source plus feedback actual-character cap exceeded")
        messages += [{"role":"assistant","content":draft_text},{"role":"user","content":protocol["verify_instruction"]+"\n程序坐标检查："+feedback}]
        final=transport.fetch(folder,"final",qa.request(messages,final=True),transport.SECRET)
        compiled={"status":"incomplete","answer":None,"answer_text":None}
        try:
            choice=qa.choice(final)
            if choice["finish_reason"]!="stop":
                raise ValueError("final response truncated")
            answer=validate(qa.decode_json_prefix(choice["message"]["content"]),packet["delivery"])
            compiled={"status":"complete_structure","answer":answer,"answer_text":answer_text(answer,packet["delivery"])}
        except (ValueError,TypeError,KeyError) as error:
            compiled["error"]=str(error)
        save(folder/"compiled.json",{**compiled,"packet_sha256":expected,"draft_response_sha256":sha(folder/"draft.json"),
             "final_response_sha256":sha(folder/"final.json"),"protocol_sha256":sha(protocol_file),
             "limits":"complete_structure means literal source-coordinate validation only, not correctness or complete answer"})
        print("DONE",key,compiled["status"],flush=True)
    save(args.output/"completion.json",{"sessions":24,"protocol_sha256":sha(protocol_file),"status":"complete"})


if __name__=="__main__":
    main()
