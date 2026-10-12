"""开发盲评分状态与成本汇总；无效评分保留未知，不抹去答案失败。"""
import argparse
from collections import Counter,defaultdict
import hashlib
import json
from pathlib import Path


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--review",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args()
    if args.output.exists():
        raise FileExistsError("new review summary required")
    if not (args.review/"completion.json").exists():
        raise ValueError("finish blind review grid")
    protocol_file=args.review/"protocol.json"
    protocol=json.loads(protocol_file.read_text())
    identity_file=args.review/"evaluation_only/identity.json"
    identity=json.loads(identity_file.read_text())
    status,usage=Counter(),Counter()
    attempts,rows,errors=0,[],[]
    for key,expected in protocol["packets"].items():
        packet=args.review/"packets"/(key+".json")
        folder=args.review/"responses"/key
        compiled_file,response_file=folder/"compiled.json",folder/"review.json"
        compiled=json.loads(compiled_file.read_text())
        response=json.loads(response_file.read_text())
        meta=identity[key]
        if sha(packet)!=expected or compiled["packet_sha256"]!=expected or compiled["response_sha256"]!=sha(response_file) or compiled["protocol_sha256"]!=sha(protocol_file) or sha(Path(meta["answer_file"]))!=meta["answer_sha256"]:
            raise ValueError("blind review input/response drift")
        if response["request"]["model"]!=protocol["model"] or response["raw_response"]["model"]!=protocol["model"]:
            errors.append(key)
        if response["request"]["temperature"]!=0 or response["request"]["enable_thinking"] is not False or response["request"]["max_tokens"]!=2400 or response["request"]["response_format"]!={"type":"json_object"}:
            raise ValueError("review model generation drift")
        usage.update(response["raw_response"].get("usage",{}))
        attempts+=len(response["events"])
        status[compiled["status"]]+=1
        if meta["answer_structure"]!="complete_structure":
            outcome="failed_answer_structure_or_citation"
        elif compiled["status"]!="valid_structure":
            outcome="unknown_invalid_judge"
        elif compiled["model_strict_success"]:
            outcome="model_claimed_success"
        else:
            outcome="model_claimed_failure"
        rows.append({"blind_id":key,**meta,"judge_status":compiled["status"],"judge_error":compiled.get("error"),
                     "model_strict_success":compiled["model_strict_success"],"outcome":outcome,
                     "review_sha256":sha(compiled_file),"point_reviews":compiled.get("review",{}).get("points",[])})
    grouped=defaultdict(list)
    for row in rows:
        grouped[row["category"],row["arm"]].append(row)
    summaries=[]
    for (category,arm),group in sorted(grouped.items()):
        counts=Counter(r["outcome"] for r in group)
        positive=counts["model_claimed_success"]
        unknown=counts["unknown_invalid_judge"]
        summaries.append({"category":category,"arm":arm,"families":len(group),"sessions":len(group),
            "outcomes":dict(counts),"model_grade_rate_bounds_with_unknown":[positive/len(group),(positive+unknown)/len(group)]})
    out={"schema":"development-blind-cited-answer-summary-v1","protocol_sha256":sha(protocol_file),
        "identity_sha256":sha(identity_file),"implementation_sha256":sha(Path(__file__)),
        "role":protocol["role"],"model":protocol["model"],"planned_calls":protocol["planned_calls"],"completed_calls":len(rows),
        "judge_statuses":dict(status),"attempts":attempts,"retries":attempts-len(rows),"usage":dict(usage),
        "identity_errors":errors,"summary":summaries,"rows":rows,
        "limits":"same8B model diagnoses only; grade bounds express invalid-judge unknowns, not CI or verified strict success. Real human review and formal adjudication remain required."}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({k:v for k,v in out.items() if k!="rows"},ensure_ascii=False))


if __name__=="__main__":
    main()
