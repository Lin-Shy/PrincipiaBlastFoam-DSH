"""生成逐项审阅包并编译显式评分；不使用关键词或证据覆盖自动判答案正确。"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from experiments.retrieval_method import navigation_metrics as metrics


def read(path):
    return json.loads(path.read_text())


def save(path, value):
    if path.exists():
        raise ValueError("preserve previous review artifact; use a new path")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2)+"\n")


def packet(run, items, output):
    protocol = read(run/"protocol.json")
    for name, expected in protocol["files"].items():
        if metrics.sha((run/name).read_bytes()) != expected:
            raise ValueError("frozen artifact changed: "+name)
    annotations = {a["id"]: a for a in read(run/"evaluation_only/annotations.json")}
    questions = read(run/"questions.json")
    rows = []
    for qid in items:
        a = annotations[qid]
        sessions = []
        for folder in sorted((run/"sessions").glob(qid+"-p*")):
            if not (folder/"result.json").exists():
                continue
            result = read(folder/"result.json")
            m = metrics.session_metrics(folder, a)
            seen = result["seen_lines"]
            citations = []
            for i, ref in enumerate(result.get("parsed_answer", {}).get("references", [])):
                path = ref.get("path", "")
                start, end = ref.get("start", 0), ref.get("end", 0)
                source = (run/"skill/corpus"/path).resolve()
                valid = source.is_relative_to((run/"skill/corpus").resolve()) and source.is_file()
                raw = source.read_text().splitlines() if valid else []
                citations.append({"index":i, **ref, "range_check":m["citation_range_checks"][i],
                    "original": [f"{n}: {raw[n-1]}" for n in range(start,end+1) if 1<=n<=len(raw)],
                    "unseen_lines":[n for n in range(start,end+1) if str(n) not in seen.get(path,{})]})
            covered = []
            for ev in a["evidence"]:
                covered.append({"id":ev["id"],"path":ev["path"],
                    "seen_lines":{n:text for n,text in seen.get(ev["path"],{}).items() if ev["start"]<=int(n)<=ev["end"]}})
            sessions.append({"session":folder.name,"answer":result["parsed_answer"],"citations":citations,
                "necessary_evidence_seen":covered,
                "identity":{key:m[key] for key in ("answer_sha256","trace_sha256","annotation_sha256")},
                "trace_actions":[e["action"] for e in result["events"] if "result" in e]})
        rows.append({"annotation":a,"questions":[q for q in questions if q["id"].startswith(qid+"-")],"sessions":sessions})
    save(output,{"run":str(run.resolve()),"protocol_sha256":metrics.sha((run/"protocol.json").read_bytes()),
                 "reviewer_constraint":"Only explicit source-grounded reviewer decisions may become scores; not independent author-blind grading.","items":rows})


def compile_reviews(packet_path, decisions, output):
    raw = read(packet_path); authored = read(decisions)
    if authored["packet_sha256"] != metrics.sha(packet_path.read_bytes()):
        raise ValueError("review packet identity changed")
    run=Path(raw["run"]); rules=read(run/"evaluation_only/scoring-rules.json")
    if raw["protocol_sha256"] != metrics.sha((run/"protocol.json").read_bytes()):
        raise ValueError("review run changed")
    lookup={s["session"]:(item["annotation"],s) for item in raw["items"] for s in item["sessions"]}
    compiled=[]
    for selected in authored["sessions"]:
        template=authored.get("templates",{}).get(selected.get("template"),{})
        decision={**template,**selected,"dimensions":{**template.get("dimensions",{}),**selected.get("dimensions",{})}}
        session=decision["session"]; annotation,p=lookup[session]
        folder=run/"sessions"/session; result=read(folder/"result.json"); seen=result["seen_lines"]
        m=metrics.session_metrics(folder,annotation)
        for key,value in p["identity"].items():
            if m[key]!=value:
                raise ValueError("answer/trace changed since review")
        points=[]
        for point in decision["gold_points"]:
            support=[]
            for requested in point.get("support",[]):
                if isinstance(requested,list):
                    requested=dict(zip(("path","start","end"),requested))
                path,start,end=requested["path"],requested["start"],requested["end"]
                path=authored.get("paths",{}).get(path,path)
                if not all(str(n) in seen.get(path,{}) for n in range(start,end+1)):
                    raise ValueError("reviewer selected unseen source")
                support.append({"path":path,"start":start,"end":end,
                    "quote":"\n".join(seen[path][str(n)] for n in range(start,end+1))})
            points.append({**point,"support":support})
        review={**decision,**p["identity"],"gold_points":points,"reviewer":authored["reviewer"],
            "packet_sha256":authored["packet_sha256"],"authored_decisions_sha256":metrics.sha(decisions.read_bytes())}
        metrics.merge_review(m,review,annotation,rules,seen)
        compiled.append(review)
    save(output,compiled)


def merge_reviews(inputs,output):
    rows=[]; sessions=set()
    for path in inputs:
        for row in read(path):
            if row['session'] in sessions:
                raise ValueError('duplicate review session: '+row['session'])
            if not all(row.get(k) for k in ('answer_sha256','trace_sha256','annotation_sha256','packet_sha256','authored_decisions_sha256')):
                raise ValueError('only compiled identity-bound reviews can be merged')
            sessions.add(row['session']);rows.append(row)
    save(output,rows)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("command",choices=("packet","compile","merge"))
    p.add_argument("--run",type=Path)
    p.add_argument("--items",nargs="+")
    p.add_argument("--packet",type=Path)
    p.add_argument("--decisions",type=Path)
    p.add_argument("--inputs",type=Path,nargs='+')
    p.add_argument("--output",type=Path,required=True)
    a=p.parse_args()
    if a.command=="packet":packet(a.run,a.items,a.output)
    elif a.command=="compile":compile_reviews(a.packet,a.decisions,a.output)
    else:merge_reviews(a.inputs,a.output)
    print(str(a.output))


if __name__=="__main__":main()
