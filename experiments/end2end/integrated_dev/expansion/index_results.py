"""Build the public-task evidence index. Grade only sealed submissions."""
from collections import defaultdict
import json
from verify_public import check
from wave import ARMS,DATA,OUT,read,sha,write


def build():
    selection=set(read(OUT/"intake.json")["selected"]+read(OUT/"intake_families.json")["selected"])
    if (OUT/"remaining_variants.json").exists():
        selection.update(t for batch in read(OUT/"remaining_variants.json")["batches"] for t in batch)
    rows=[]
    summary=defaultdict(lambda:dict(planned=0,issued=0,started=0,sealed=0,first_passed=0,passed=0,
        first_empty=0,continuations=0,requests=0,tokens_reported=0,unknown_usage=0,node_jobs=0,node_seconds=0))
    lines=["# 扩充开发题公开包、运行、交件与验收索引","",
        "按家族变体分四批，批内遵循 READY 顺序。两臂使用同一公开 ZIP。每题每臂计一次，首次和最终评分均以计划题数为分母。续接继承原请求账本与作业额度，成本使用累计值。首次空包及后续封存分别保留。","",
        "| 公开题 | 家族／层次 | 原始 DSH | 专业系统 |","|---|---|---|---|"]
    for item in read(DATA/"READY.json")["tasks"]:
        task=item["id"]
        public="../../../../graduation-datasets/chapter03_simulation_tasks/expansion_20261121/"+item["archive"]
        row=dict(task=task,family=item["family"],stratum=item["stratum"],public_archive=public,
                 public_sha256=item["sha256"],selected=task in selection,arms={})
        labels=[]
        for arm in ARMS:
            root=OUT/task/arm
            rel=f"{task}/{arm}"
            if task not in selection:
                row["arms"][arm]=dict(status="not_dispatched",reason="本轮按家族各取首包；该题为后续变体")
                labels.append("未派发，同族后续变体")
                continue
            totals=summary[(item["stratum"],arm)]
            totals["planned"]+=1
            totals["issued"]+=int((root.parent/"manifest.json").exists())
            totals["started"]+=int((root/"attempt_intent.json").exists())
            records=[]
            for segment in (None,"continuation"):
                location=root/segment if segment else root
                if not (location/"sealed.json").exists():
                    continue
                prefix=rel+("/continuation" if segment else "")
                receipt=read(location/"sealed.json")
                try:
                    verdict=check(task,arm,segment)
                except (KeyError,TypeError,ValueError,FileNotFoundError) as exc:
                    verdict=dict(passed=False,reason=str(exc))
                score=dict(task=task,arm=arm,segment=segment or "first",public_sha256=item["sha256"],
                           submission_sha256=receipt["archive_sha256"],**verdict)
                path=location/"public_score.json"
                if path.exists():
                    if read(path)!=score:
                        raise ValueError("existing public score changed")
                else:
                    write(path,score)
                records.append(dict(segment=segment or "first",seal=prefix+"/sealed.json",submission=prefix+"/submission.zip",
                                    score=prefix+"/public_score.json",passed=verdict["passed"],requests=receipt["requests"],
                                    reported_tokens=receipt["tokens_reported"],unknown_usage=receipt["unsettled"]))
            result=dict(status="sealed" if records else ("started" if (root/"attempt_intent.json").exists() else ("prepared" if root.exists() else "queued")),
                        segments=records)
            if (root/"operator/job_receipt.json").exists():
                totals["node_jobs"]+=1
                result["submitted_job"]=read(root/"operator/job_receipt.json")["job_id"]
            if (root/"operator/verified.json").exists():
                node=read(root/"operator/verified.json")
                h,m,s=map(int,node["elapsed"].split(":"))
                totals["node_seconds"]+=h*3600+m*60+s
                result["node"]=dict(job_id=node["job_id"],receipt=rel+"/operator/verified.json",
                    submit=rel+"/operator/job_receipt.json",status=rel+"/operator/status.jsonl",elapsed=node["elapsed"])
            row["arms"][arm]=result
            if not records:
                labels.append(result["status"])
                continue
            last=records[-1]
            totals["first_passed"]+=int(records[0]["passed"])
            totals["first_empty"]+=int(not read(root/"sealed.json")["files"])
            totals["continuations"]+=int(len(records)>1)
            totals["sealed"]+=1
            totals["passed"]+=int(last["passed"])
            totals["requests"]+=last["requests"]
            totals["tokens_reported"]+=last["reported_tokens"]
            totals["unknown_usage"]+=len(last["unknown_usage"])
            label=("通过" if last["passed"] else "未通过")+("（续接）" if len(records)>1 else "")
            links=[f"[{label}]({last['score']})",f"[交件]({last['submission']})",f"[用量]({last['seal']})"]
            if len(records)>1:
                links.extend([f"[首次评分]({records[0]['score']})",f"[首次封存]({records[0]['seal']})"])
            if "node" in result:
                links.append(f"[{result['node']['job_id']}]({result['node']['receipt']})")
            labels.append(" · ".join(links))
        rows.append(row)
        lines.append(f"| [{task}]({public}) | {item['family']}／{item['stratum']} | "+" | ".join(labels)+" |")
    lines+=["","| 层次 | 系统 | 计划 | 已派发 | 已启动 | 已封存 | 首次通过 | 最终通过 | 首次空包 | 续接 | 累计请求 | 已报告 token | 用量未知 | 节点作业 | 已核验节点秒 |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for (stratum,arm),s in summary.items():
        lines.append(f"| {stratum} | {arm} | "+" | ".join(str(s[k]) for k in s)+" |")
    cumulative={}
    for arm in ARMS:
        groups=[s for (stratum,a),s in summary.items() if a==arm]
        cumulative[arm]={k:sum(s[k] for s in groups) for k in groups[0]}
        lines.append(f"| 全部 | {arm} | "+" | ".join(str(v) for v in cumulative[arm].values())+" |")
    lines+=["","两套系统实际金额均未知。每个单元格的作业编号只对应本题本臂。工程读出与审核均不占用计算节点。"]
    (OUT/"INDEX.md").write_text("\n".join(lines)+"\n",encoding="utf8")
    (OUT/"index.json").write_text(json.dumps(dict(ready_sha256=sha(DATA/"READY.json"),tasks=rows,
        summary={f"{k[0]}/{k[1]}":v for k,v in summary.items()},cumulative=cumulative),ensure_ascii=False,indent=2),encoding="utf8")


if __name__=="__main__":
    build()
