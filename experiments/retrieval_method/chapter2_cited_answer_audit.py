"""冻结回答零模型重放、权威原文与调用身份/成本审计。"""
import argparse
from collections import Counter
import hashlib
import importlib
import json
from pathlib import Path
import sys

from chapter2_production_guard import install


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ("answers","corpus","output"):
        p.add_argument("--"+name,type=Path,required=True)
    args=p.parse_args()
    if args.output.exists():
        raise FileExistsError("new audit artifact required")
    guard=install(offline=True)
    if not (args.answers/"completion.json").exists():
        raise ValueError("complete answer grid before replay")
    protocol_file=args.answers/"protocol.json"
    protocol=json.loads(protocol_file.read_text())
    runtime=args.answers/"runtime"
    for name,expected in protocol["runtime_sha256"].items():
        if sha(runtime/name)!=expected:
            raise ValueError("answer runtime drift")
    sys.path.insert(0,str(runtime.resolve()))
    model=importlib.import_module("chapter2_cited_answer")
    qa=importlib.import_module("navigation_qa")
    importlib.import_module("chapter2_aliyun_config").configure_qa(qa)
    if Path(model.__file__).resolve()!= (runtime/"chapter2_cited_answer.py").resolve():
        raise ValueError("wrong frozen answer replay module")
    sources,rows={},[]
    usage,status,draft_status=Counter(),Counter(),Counter()
    attempts,checked,identity_errors=0,0,[]
    for key,expected in protocol["packets"].items():
        packet_file=args.answers/"packets"/(key+".json")
        if sha(packet_file)!=expected:
            raise ValueError("answer packet drift")
        packet=json.loads(packet_file.read_text())
        if packet["question"]["split"]!="dev":
            raise ValueError("development audit only")
        delivery=packet["delivery"]
        if len(delivery["text"])!=delivery["returned_characters"] or len(delivery["text"])>protocol["return_character_cap"]:
            raise ValueError("actual delivered-character accounting")
        blocks=[]
        for unit in delivery["units"]:
            if unit.get("mapping_status") == "unmappable":
                if "citation_id" in unit:
                    raise ValueError("unmappable result made citable")
                continue
            path=unit["path"]
            if path not in sources:
                file=(args.corpus/path).resolve()
                if not file.is_relative_to(args.corpus.resolve()):
                    raise ValueError("source outside corpus")
                raw=file.read_bytes()
                sources[path]=(hashlib.sha256(raw).hexdigest(),raw.decode().splitlines())
            source_hash,lines=sources[path]
            if source_hash!=unit["source_sha256"] or lines[unit["start"]-1:unit["end"]]!=unit["lines"]:
                raise ValueError("delivered authoritative source drift")
            checked+=len(unit["lines"])
            # requested范围来自未截断 canonical 单元，实际证据只由完整行定义。
            header_start=delivery["text"].find(f"\n[{unit['citation_id']}] {path} sha256={source_hash} requested_lines=")
            if header_start<0:
                raise ValueError("missing delivered source header")
            block_start=delivery["text"].find("\n",header_start+1)+1
            exact="".join(f"{i}: {line}\n" for i,line in enumerate(unit["lines"],unit["start"]))
            if delivery["text"][block_start:block_start+len(exact)]!=exact:
                raise ValueError("raw source text mismatch")
        folder=args.answers/"responses"/key
        compiled_file=folder/"compiled.json"
        compiled=json.loads(compiled_file.read_text())
        response={stage:json.loads((folder/(stage+".json")).read_text()) for stage in ("draft","final")}
        for stage,a in response.items():
            request=a["request"]
            if request["model"]!=protocol["model"] or a["raw_response"]["model"]!=protocol["model"]:
                identity_errors.append(key+"/"+stage)
            if request["temperature"]!=0 or request["enable_thinking"] is not False or request["max_tokens"]!=2400 or request["response_format"]!={"type":"json_object"}:
                raise ValueError("answer generation drift")
            usage.update(a["raw_response"].get("usage",{}))
            attempts+=len(a["events"])
            if compiled[stage+"_response_sha256"]!=sha(folder/(stage+".json")):
                raise ValueError("compiled response drift")
        messages=[{"role":"system","content":protocol["draft_instruction"]},
                  {"role":"user","content":"公开问题："+packet["question"]["question"]+"\n权威原文：\n"+delivery["text"]}]
        if response["draft"]["request"]["messages"]!=messages:
            raise ValueError("draft prompt/context drift")
        draft_choice=qa.choice(response["draft"])
        feedback = model.verification_feedback(response["draft"], delivery, qa) if protocol.get("feedback_character_reserve") else None
        if feedback is not None and len(feedback)+len("程序坐标检查：")+delivery["returned_characters"]>protocol["return_character_cap"]:
            raise ValueError("actual source plus diagnostic budget exceeded")
        verification = protocol["verify_instruction"]+("\n程序坐标检查："+feedback if feedback is not None else "")
        messages+=[{"role":"assistant","content":draft_choice["message"]["content"]},{"role":"user","content":verification}]
        if response["final"]["request"]["messages"]!=messages:
            raise ValueError("verification prompt/context drift")
        try:
            if draft_choice["finish_reason"]!="stop":
                raise ValueError("draft truncated")
            model.validate(qa.decode_json_prefix(draft_choice["message"]["content"]),delivery)
            draft_status["valid_structure"]+=1
        except (ValueError,TypeError,KeyError):
            draft_status["invalid_structure"]+=1
        replay={"status":"incomplete","answer":None,"answer_text":None}
        try:
            choice=qa.choice(response["final"])
            if choice["finish_reason"]!="stop":
                raise ValueError("final response truncated")
            answer=model.validate(qa.decode_json_prefix(choice["message"]["content"]),delivery)
            replay={"status":"complete_structure","answer":answer,"answer_text":model.answer_text(answer,delivery)}
        except (ValueError,TypeError,KeyError) as error:
            replay["error"]=str(error)
        if any(compiled.get(k)!=v for k,v in replay.items()) or compiled["protocol_sha256"]!=sha(protocol_file) or compiled["packet_sha256"]!=expected:
            raise ValueError("zero-model replay mismatch")
        status[compiled["status"]]+=1
        rows.append({"id":key,"arm":packet["arm"],"family_id":packet["question"]["family_id"],
                     "status":compiled["status"],"error":compiled.get("error"),"replay":"pass",
                     "compiled_sha256":sha(compiled_file),"returned_characters":delivery["returned_characters"]})
    out={"schema":"development-cited-answer-source-and-replay-audit-v1","protocol_sha256":sha(protocol_file),
         "implementation_sha256":sha(Path(__file__)),"guard":guard,"sessions":len(rows),"replay_passes":len(rows),
         "statuses":dict(status),"draft_statuses":dict(draft_status),"model_calls_observed":len(rows)*2,
         "audit_model_calls":0,"attempts":attempts,"retries":attempts-len(rows)*2,"usage":dict(usage),
         "identity_errors":identity_errors,"source_files_checked":len(sources),"source_lines_checked":checked,"rows":rows,
         "limits":"source-coordinate/protocol replay only; complete_structure does not imply semantic or strict answer success"}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({k:v for k,v in out.items() if k!="rows"},ensure_ascii=False))


if __name__=="__main__":
    main()
