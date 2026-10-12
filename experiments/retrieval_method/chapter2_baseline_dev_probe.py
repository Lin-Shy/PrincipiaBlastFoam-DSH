"""独立基线原生适配连通检查；公开开发材料，禁止读取gold。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import time


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path,value):
    if path.exists():
        raise FileExistsError("new artifact required")
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+"\n")


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("command",choices=("prepare","run"))
    p.add_argument("--arm",choices=("no_graph","graphify_native","graphify_text_adapter","e5"),required=True)
    for name in ("planner","corpus","corpus-manifest","output"):
        p.add_argument("--"+name,type=Path,required=True)
    for name in ("graph","path-map","index","upstream"):
        p.add_argument("--"+name,type=Path)
    args=p.parse_args()
    if os.environ.get("PYTHONHASHSEED")!="0":
        raise ValueError("set PYTHONHASHSEED=0")
    # 本过程仅为独立E5；框架预载不进入自研进程，不加载模型或语料。
    preload_started=time.monotonic()
    if args.arm=="e5" and args.command=="run":
        os.environ["HF_HUB_OFFLINE"]="1"
        import torch
        import sentence_transformers
    framework_preload_seconds=time.monotonic()-preload_started
    if args.upstream:
        sys.path.insert(0,str(args.upstream.resolve()))
    from chapter2_production_guard import install
    guard=install(offline=True)
    planner_file=args.planner/"protocol.json"
    planner=json.loads(planner_file.read_text())
    if planner["model"]!="qwen3-8b" or planner["role"]!="common_query_planning_development":
        raise ValueError("same public8B development planner required")
    questions=[q for q in json.loads((args.planner/"questions.json").read_text()) if q["id"] in {"F001-n1","F009-n1","F045-n1"}]
    if len(questions)!=3 or any(q["split"]!="dev" for q in questions):
        raise ValueError("three predetermined public development questions")
    plans,hashes={},{}
    for q in questions:
        f=args.planner/"responses"/q["id"]/"compiled.json"
        compiled=json.loads(f.read_text())
        if compiled["question"]!=q or compiled["protocol_sha256"]!=sha(planner_file) or compiled["response_sha256"]!=sha(f.parent/"plan.json"):
            raise ValueError("shared planning drift")
        plans[q["id"]]=compiled["plan"]
        hashes[q["id"]]=sha(f)
    inputs={"planner_protocol":sha(planner_file),"corpus_manifest":sha(args.corpus_manifest)}
    for name in ("graph","path_map"):
        if getattr(args,name):
            inputs[name]=sha(getattr(args,name))
    if args.index:
        inputs["index_manifest"]=sha(args.index/"manifest.json")
    if args.upstream:
        inputs["upstream_serve"]=sha(args.upstream/"graphify/serve.py")
    runtime=Path(__file__).parent
    names=(Path(__file__).name,"chapter2_baseline_native.py","chapter2_production_guard.py","candidate_graph_utils.py",
           "candidate_hybrid.py","chapter2_canonical_delivery.py","canonical_evidence_v1.py")
    if args.command=="prepare":
        if args.output.exists():
            raise FileExistsError("new baseline development version")
        for name in names:
            dest=args.output/"runtime"/name
            dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(runtime/name,dest)
        save(args.output/"protocol.json",{"schema":"development-baseline-native-adapter-probe-v1","major_round":3,
            "arm":args.arm,"questions":questions,"plans_sha256":hashes,"inputs_sha256":inputs,"guard":guard,
            "native_limit":64,"budgets":[6000,12000,24000],"runtime_sha256":{name:sha(runtime/name) for name in names},
            "query_policy":"same unchanged public question + shared8B translation/needs as self arms",
            "model_calls":0,"limits":"three-question adapter connectivity/source check only; not a quality comparison or new method-tuning round"})
        return
    if runtime.resolve()!=(args.output/"runtime").resolve():
        raise ValueError("run frozen baseline adapter snapshot")
    protocol_file=args.output/"protocol.json"
    protocol=json.loads(protocol_file.read_text())
    if protocol["arm"]!=args.arm or protocol["plans_sha256"]!=hashes or protocol["inputs_sha256"]!=inputs:
        raise ValueError("baseline adapter inputs drift")
    for name,expected in protocol["runtime_sha256"].items():
        if sha(runtime/name)!=expected:
            raise ValueError("baseline runtime drift")
    from chapter2_baseline_native import NoGraphBM25,DenseE5,GraphifyNative
    from chapter2_canonical_delivery import canonicalize,render
    started=time.monotonic()
    if args.arm=="no_graph":
        engine=NoGraphBM25(args.corpus,args.corpus_manifest)
    elif args.arm=="e5":
        engine=DenseE5(args.corpus,args.corpus_manifest,args.index)
    else:
        engine=GraphifyNative(args.corpus,args.corpus_manifest,args.graph,args.path_map)
    load_seconds=time.monotonic()-started
    for q in questions:
        output=args.output/"responses"/(q["id"]+".json")
        if output.exists():
            if json.loads(output.read_text())["protocol_sha256"]!=sha(protocol_file):
                raise ValueError("existing response drift")
            continue
        packet,diagnostic=engine.query(q["question"],plans[q["id"]],protocol["native_limit"])
        units=canonicalize(packet,diagnostic["seconds"])
        deliveries={str(b):render(units,b) for b in protocol["budgets"]}
        save(output,{"question":q,"arm":args.arm,"mapped_native":packet,"canonical_units":units,"deliveries":deliveries,
                     "diagnostic":diagnostic,"load_seconds":load_seconds,"framework_preload_seconds":framework_preload_seconds,
                     "protocol_sha256":sha(protocol_file),"guard":guard})
        print("DONE",args.arm,q["id"],"seconds",round(diagnostic["seconds"],4),"units",len(units),flush=True)
    save(args.output/"completion.json",{"status":"complete","queries":3,"model_calls":0,"protocol_sha256":sha(protocol_file)})


if __name__=="__main__":
    main()
