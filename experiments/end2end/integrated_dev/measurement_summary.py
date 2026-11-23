"""Verify diagnostic receipts and emit the cumulative development-only scorecard."""
from collections import Counter
from pathlib import Path
import hashlib
import json
import zipfile
from measurement_live import DATA, OUT, HERE, read, sha, write


def summarize():
    rows = []
    for item in read(DATA/"READY.json")["tasks"]:
        root = OUT/"live"/item["id"]/"professional"
        manifest = read(root.parent/"manifest.json")
        assert all(sha(Path(p))==digest for p,digest in manifest["source_sha256"].items())
        with zipfile.ZipFile(DATA/item["archive"]) as package:
            assert all(package.read(name)==(root/"workspace"/name).read_bytes() for name in package.namelist())
        receipt, grade = read(root/"sealed.json"), read(root/"grade.json")
        assert receipt["archive_sha256"]==sha(root/"submission.zip")
        if "report_sha256" in grade:

            with zipfile.ZipFile(root/"submission.zip") as z:
                assert hashlib.sha256(z.read("report.json")).hexdigest()==grade["report_sha256"]
        calls = Counter()
        sessions = set()
        for line in (root/"native_events.jsonl").read_text(encoding="utf8").splitlines():
            record = json.loads(line)
            sessions.add(record["session_id"])
            event = record["event"]
            if event["type"]=="tool/call":
                calls[event["data"]["name"]]+=1
        toolnames = ("convert_volume_rates","interval_coverage","latest_attempt_events")
        rows.append(dict(item=item,manifest_sha256=sha(root.parent/"manifest.json"),receipt=receipt,
                    grade=grade,session_ids=sorted(sessions),tool_calls={k:calls[k] for k in toolnames},
                    grader_sha256=read(DATA/"READY.json")["judge_sha256"]))
    sums = {}
    for dimension in ("stratum","exposure"):
        groups = {}
        for row in rows:
            group = groups.setdefault(row["item"][dimension],dict(passed=0,total=0))
            group["total"]+=1
            group["passed"]+=int(row["grade"]["passed"])
        sums[dimension]=groups
    costs = {k:sum(row["receipt"][k] for row in rows) for k in ("requests","tokens_reported","unknown_usage","cluster_jobs")}
    paths = ["measurement-audit.mjs","measurement_profile.py","measurement-review/SKILL.md",
             "measurement_live.py","measurement_replay.py","measurement_summary.py","start.py"]
    with zipfile.ZipFile(OUT/"revision.zip","x",compression=zipfile.ZIP_DEFLATED) as archive:
        for name in paths:
            archive.write(HERE/name,name)
    write(OUT/"index.json",dict(dataset_ready_sha256=sha(DATA/"READY.json"),version_sha256=sha(OUT/"revision.zip"),
          offline_replays=3,live=rows,groups=sums,cost=dict(costs,money=None)))
    with (OUT/"RESULT.md").open("a",encoding="utf8") as f:
        f.write("\n| 题号 | 任务族 | 公开字段全通过 | 专项工具实际调用 | 请求 | 已报告 token |\n|---|---|---|---|---:|---:|\n")
        for row in rows:
            item,receipt=row["item"],row["receipt"]
            calls="、".join(f"{k} × {v}" for k,v in row["tool_calls"].items() if v) or "0"
            f.write(f"| [{item['id']}](live/{item['id']}/professional/grade.json) | {item['family']} | {row['grade']['passed']} | {calls} | {receipt['requests']} | {receipt['tokens_reported']:,} |\n")
        f.write(f"\n共 {costs['requests']} 次模型请求，已报告 {costs['tokens_reported']:,} 个 token，用量未知 {costs['unknown_usage']} 次，实际账单金额未知。分层成绩、版本哈希、模型调用与封存包对应关系见[机器索引](index.json)。\n")
    print(json.dumps(dict(groups=sums,cost=costs)))


if __name__=="__main__":
    summarize()

