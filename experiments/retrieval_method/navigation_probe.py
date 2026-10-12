"""相同开发问题/既有定位动作的离线结构消融；不生成答案、不访问金标准。"""
from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
import time


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run",type=Path,required=True)
    p.add_argument("--traces",type=Path)
    p.add_argument("--output",type=Path,required=True)
    args=p.parse_args(); run=args.run.resolve()
    spec=importlib.util.spec_from_file_location("frozen_probe_runner",run/"runner.py")
    qa=importlib.util.module_from_spec(spec); spec.loader.exec_module(qa)
    protocol=qa.verify(run)
    if protocol["split"]!="dev":
        raise ValueError("development probe cannot access heldout questions")
    args.output.mkdir(parents=True,exist_ok=False)
    questions={q["id"]:q for q in qa.read(run/"questions.json")}
    tasks=[{"id":qid+"--initial","question":q["question"],"action":{"action":"locate"},
            "cap":protocol["limits"]["per_tool_characters"]} for qid,q in questions.items()]
    trace_hashes={}
    if args.traces:
        original=qa.verify(args.traces)
        if original["split"]!="dev" or qa.read(args.traces/"questions.json")!=list(questions.values()):
            raise ValueError("trace questions/split mismatch")
        for path in sorted((args.traces/"sessions").glob("*/result.json")):
            result=qa.read(path); used=0
            trace_hashes[path.parent.name]=qa.digest(path.read_bytes())
            for event in result["events"]:
                cap=min(protocol["limits"]["per_tool_characters"],protocol["limits"]["returned_characters"]-used)
                if event["action"].get("action")=="locate":
                    tasks.append({"id":path.parent.name+"--step-"+str(event["step"]),
                        "question":result["question"],"action":event["action"],"cap":cap})
                used+=event.get("returned_characters",0)
    qa.write(args.output/"protocol.json",{"runner_sha256":qa.digest((run/"runner.py").read_bytes()),
        "probe_sha256":qa.digest(Path(__file__).read_bytes()),"run_protocol_sha256":qa.digest((run/"protocol.json").read_bytes()),
        "source_trace_hashes":trace_hashes,"tasks":tasks,"model_calls":0,
        "scope":"offline same-action navigation comparison, not an agent answer-quality evaluation"})
    qa.instrument_file_reads(); engine=qa.Engine(run); summary=[]
    for task in tasks:
        session=qa.Session(engine,"graph_first",task["question"])
        result,accounting=session.dispatch(task["action"],task["cap"])
        qa.write(args.output/(task["id"]+".json"),{"task":task,"result":result,"accounting":accounting,"seen_lines":session.seen})
        summary.append({"id":task["id"],"status":result["status"],"locations":len(result.get("locations",[])),
                        "returned_characters":len(qa.wire(result)),"seconds":accounting["seconds"]})
    qa.verify(run)
    qa.write(args.output/"summary.json",{"tasks":len(tasks),"results":summary,"model_calls":0,"model_tokens":0})
    print(json.dumps({"tasks":len(tasks),"output":str(args.output)},ensure_ascii=False))


if __name__=="__main__":main()
