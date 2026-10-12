"""逐要求评分汇总，保留无效/不确定评分及答案确定性失败的区别。"""
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
        raise FileExistsError("new summary required")
    if not (args.review/"completion.json").exists():
        raise ValueError("complete pointwise grid first")
    protocol_file=args.review/"protocol.json"
    protocol=json.loads(protocol_file.read_text())
    identity_file=args.review/"evaluation_only/identity.json"
    identity=json.loads(identity_file.read_text())
    status,labels,usage=Counter(),Counter(),Counter()
    attempts,errors=0,[]
    grouped=defaultdict(list)
    for key,job in protocol["jobs"].items():
        folder=args.review/"responses"/key
        f=folder/"compiled.json"
        compiled=json.loads(f.read_text())
        response_file=folder/"review.json"
        response=json.loads(response_file.read_text())
        if sha(args.review/"packets"/(key+".json"))!=job["packet_sha256"] or compiled["packet_sha256"]!=job["packet_sha256"] or compiled["response_sha256"]!=sha(response_file) or compiled["protocol_sha256"]!=sha(protocol_file):
            raise ValueError("pointwise response provenance drift")
        if response["request"]["model"]!=protocol["model"] or response["raw_response"]["model"]!=protocol["model"]:
            errors.append(key)
        if response["request"]["max_tokens"]!=700 or response["request"]["enable_thinking"] is not False or response["request"]["temperature"]!=0:
            raise ValueError("pointwise generation drift")
        status[compiled["status"]]+=1
        attempts+=len(response["events"])
        usage.update(response["raw_response"].get("usage",{}))
        if compiled["review"]:
            labels[compiled["review"].get("assessment",compiled["review"].get("state"))]+=1
        grouped[job["blind_id"]].append({"job":key,**job,**compiled,"compiled_sha256":sha(f)})
    rows=[]
    for key,meta in identity.items():
        reviews=grouped[key]
        if sha(Path(meta["answer_file"]))!=meta["answer_sha256"]:
            raise ValueError("answer changed during review")
        negatives=[]
        unknown=[]
        for r in reviews:
            v=r["review"]
            if r["status"]!="valid_structure":
                unknown.append(r["job"])
            elif r["kind"]=="point" and (v["assessment"]!="satisfied" or v["support"]!="supported"):
                negatives.append(r["job"])
            elif r["kind"]=="citations" and v["state"]=="unsupported":
                negatives.append(r["job"])
            elif r["kind"]=="citations" and v["state"]=="uncertain":
                unknown.append(r["job"])
        if meta["answer_structure"]!="complete_structure":
            outcome,interval="failed_answer_structure_or_citation",[0,0]
        elif negatives:
            outcome,interval="model_claimed_failure",[0,0]
        elif unknown:
            outcome,interval="unknown_invalid_or_uncertain_judge",[0,1]
        else:
            outcome,interval="model_claimed_success",[1,1]
        rows.append({"blind_id":key,**meta,"outcome":outcome,"model_grade_bounds":interval,
                     "negative_jobs":negatives,"unknown_jobs":unknown,"reviews":reviews})
    summaries=[]
    groups=defaultdict(list)
    for row in rows:
        groups[row["category"],row["arm"]].append(row)
    for (category,arm),rs in sorted(groups.items()):
        summaries.append({"category":category,"arm":arm,"families":len(rs),"sessions":len(rs),
            "outcomes":dict(Counter(r["outcome"] for r in rs)),
            "model_grade_rate_bounds":[sum(r["model_grade_bounds"][i] for r in rs)/len(rs) for i in (0,1)]})
    out={"schema":"development-pointwise-review-summary-v1","protocol_sha256":sha(protocol_file),
         "implementation_sha256":sha(Path(__file__)),"identity_sha256":sha(identity_file),"role":protocol["role"],
         "model":protocol["model"],"planned_calls":protocol["planned_calls"],"completed_calls":sum(status.values()),
         "statuses":dict(status),"labels":dict(labels),"attempts":attempts,"retries":attempts-sum(status.values()),
         "usage":dict(usage),"identity_errors":errors,"summary":summaries,"rows":rows,
         "limits":"same8B provisional model labels with literal answer/source traces; not verified strict success or human review. A valid negative criterion suffices for model failure; invalid remaining criteria still listed separately."}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(out,ensure_ascii=False,indent=2)+"\n")
    print(json.dumps({k:v for k,v in out.items() if k!="rows"},ensure_ascii=False))


if __name__=="__main__":
    main()
