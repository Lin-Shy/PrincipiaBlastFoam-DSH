"""补算冻结开发集首次检索调用的统一文件层排名指标。

回答模型生成的首次查询动作已经冻结；本程序不调用模型、不重跑后续导航，只把
该次调用返回的无图片段、Graphify 节点或 Principia 证据映射为权威原始文件。
因此它是 post-hoc 的 whole-system first-call 分析，而不是统一查询规划器下的纯后端榜。
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import re
import statistics

import canonical_evidence_v1 as canonical


LABELS = {
    "control": "无图",
    "native": "Graphify native",
    "text_adapter": "Graphify text-adapter",
    "principia_index_free": "Principia 候选010",
}
NODE_SOURCE = re.compile(r"^NODE .*? \[src=(.*?) loc=", re.MULTILINE)


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def first_retrieval_event(result):
    for event in result.get("events", []):
        if event.get("action", {}).get("action") in {"search", "locate"}:
            return event
    return None


def ranked_files(event):
    """Map one frozen native return to first-occurrence authoritative file order."""
    if not event or not isinstance(event.get("result"), dict):
        return []
    result = event["result"]
    ranked = []

    def add(path):
        if isinstance(path, str) and path and path != "None" and path not in ranked:
            ranked.append(path)

    for item in result.get("items", []):
        if isinstance(item, dict):
            add(item.get("path"))
    evidence, sources = result.get("evidence"), result.get("sources", {})
    if isinstance(evidence, dict) and isinstance(sources, dict):
        for item in evidence.values():
            if isinstance(item, dict):
                add(sources.get(item.get("source")))
    navigation = result.get("graph_navigation")
    if isinstance(navigation, str):
        for path in NODE_SOURCE.findall(navigation):
            add(path)
    return ranked


def aggregate(rows):
    if not rows:
        raise ValueError("empty file retrieval grid")

    def summarize(selected):
        result = {
            "questions": len(selected),
            "mrr": statistics.mean(row["metrics"]["mrr"] for row in selected),
            "first_call_returned_characters": statistics.mean(
                row["first_call_returned_characters"] for row in selected),
            "first_call_seconds": statistics.mean(
                row["first_call_seconds"] for row in selected),
            "top_k": {},
        }
        for k in canonical.DEFAULT_K:
            key = str(k)
            result["top_k"][key] = {
                metric: statistics.mean(row["metrics"]["top_k"][key][metric]
                                        for row in selected)
                for metric in ("recall", "hit_rate", "precision", "ndcg",
                               "complete_set_success")
            }
        return result

    question_mean = summarize(rows)
    families = defaultdict(list)
    for row in rows:
        families[row["family"]].append(row)
    family_rows = [summarize(group) for group in families.values()]
    family_macro = {
        "families": len(families),
        "mrr": statistics.mean(row["mrr"] for row in family_rows),
        "first_call_returned_characters": statistics.mean(
            row["first_call_returned_characters"] for row in family_rows),
        "first_call_seconds": statistics.mean(row["first_call_seconds"] for row in family_rows),
        "top_k": {},
    }
    for k in canonical.DEFAULT_K:
        key = str(k)
        family_macro["top_k"][key] = {
            metric: statistics.mean(row["top_k"][key][metric] for row in family_rows)
            for metric in ("recall", "hit_rate", "precision", "ndcg",
                           "complete_set_success")
        }
    return {"question_mean": question_mean, "family_macro": family_macro}


def evaluate(run):
    protocol = read(run / "protocol.json")
    if protocol.get("holdout_unlocked") is not False:
        raise ValueError("first-call evaluation requires a locked development protocol")
    arms = []
    annotation_hashes = {}
    for arm, methods in protocol["groups"].items():
        if len(methods) != 1:
            raise ValueError("expected one method per arm")
        method = methods[0]
        arm_root = run / arm
        annotations_path = arm_root / "evaluation_only" / "annotations.json"
        annotations = {row["id"]: row for row in read(annotations_path)}
        annotation_hashes[arm] = sha(annotations_path)
        manifest = read(arm_root / "corpus-manifest.json")
        rows = []
        for question in read(arm_root / "questions.json"):
            annotation = annotations[question["item_id"]]
            gold_files = [item["path"] for item in annotation["evidence"]]
            for replicate in range(1, protocol["replicates"] + 1):
                session = f"{question['id']}--{method}--r{replicate}"
                result_path = arm_root / "sessions" / session / "result.json"
                result = read(result_path)
                event = first_retrieval_event(result)
                files = ranked_files(event)
                outside = [path for path in files if path not in manifest]
                # Preserve the native rank penalty for Graphify image/binary or
                # otherwise unmappable paths, but never let such a path match a
                # readable authoritative gold file by accident.
                mapped_files = [
                    path if path in manifest else "__unmapped_native_path__:" + path
                    for path in files
                ]
                accounting = event.get("accounting", {}) if event else {}
                seconds = accounting.get("seconds", 0) if isinstance(accounting, dict) else 0
                returned = event.get("returned_characters", 0) if event else 0
                if not isinstance(seconds, (int, float)) or seconds < 0:
                    raise ValueError("invalid first-call latency")
                if type(returned) is not int or returned < 0:
                    raise ValueError("invalid first-call returned characters")
                rows.append({
                    "arm": arm,
                    "method": method,
                    "session": session,
                    "question_id": question["id"],
                    "family": question["item_id"],
                    "category": annotation["category"],
                    "result_sha256": sha(result_path),
                    "first_action": event.get("action") if event else None,
                    "first_call_returned_characters": returned,
                    "first_call_seconds": seconds,
                    "unmapped_native_paths": outside,
                    "metrics": canonical.score_identifier_layer(gold_files, mapped_files),
                })
        arms.append({"arm": arm, "method": method, "rows": rows,
                     "summary": aggregate(rows)})
    return {
        "schema": "first-call-canonical-file-retrieval-evaluation-v1",
        "status": "post-hoc exploratory development-set analysis",
        "scope": "first frozen search/locate call mapped to authoritative original files",
        "not_claimed": [
            "not a common-query-planner backend leaderboard",
            "not exact-line evidence retrieval",
            "not a replacement for the preregistered answer-quality gate",
            "does not unlock holdout evaluation",
        ],
        "run_protocol_sha256": sha(run / "protocol.json"),
        "implementation_sha256": {
            "first_call_file_retrieval.py": sha(Path(__file__)),
            "canonical_evidence_v1.py": sha(Path(canonical.__file__)),
        },
        "gold_annotations_sha256": annotation_hashes,
        "holdout_unlocked": False,
        "ks": list(canonical.DEFAULT_K),
        "arms": arms,
    }


def percent(value):
    return f"{100 * value:.2f}%"


def report(data):
    lines = [
        "# 第5轮首次检索调用的统一文件层分析",
        "",
        "> 本报告把四臂冻结会话的第一次 search/locate 返回统一映射为权威原始文件。查询动作由各臂回答模型在原实验中生成，因此属于 post-hoc whole-system first-call 分析，不是统一查询规划器下的纯后端排行榜。",
        "",
        "| 方法 | File Recall@1 | File Recall@3 | File Recall@5 | File Recall@10 | Complete files@10 | Hit@10 | MRR_file | nDCG@10 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for arm in data["arms"]:
        summary = arm["summary"]["family_macro"]
        top = summary["top_k"]
        lines.append("| " + " | ".join([
            LABELS.get(arm["arm"], arm["arm"]),
            percent(top["1"]["recall"]), percent(top["3"]["recall"]),
            percent(top["5"]["recall"]), percent(top["10"]["recall"]),
            percent(top["10"]["complete_set_success"]),
            percent(top["10"]["hit_rate"]), f"{summary['mrr']:.3f}",
            f"{top['10']['ndcg']:.3f}",
        ]) + " |")
    lines += [
        "",
        "## 口径限制",
        "",
        "- gold文件来自v5冻结必要证据；同一文件重复出现只保留第一次，Precision只能作为必要gold下界，未作为主表列。",
        "- Graphify节点只映射其原始 `src` 文件，不把节点标签、社区或关系当作原文；Principia证据按原始来源映射，无图搜索片段按原始路径映射。",
        "- Graphify返回的图片、二进制文件或其他不在702个可读权威文件清单中的路径保留其原生排名位置，但标为不可映射且永不计为相关，避免删除后造成乐观排名。",
        "- 文件命中不表示精确证据行已经送达。精确行段质量请使用冻结全轨迹的 canonical evidence 报告。",
        "- 下一步若要形成纯后端榜，必须在查看结果前冻结公共查询生成规则，并让各后端直接导出原生排名；本报告不能用于恢复候选迭代或打开保留集。",
    ]
    return "\n".join(lines) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    data = evaluate(args.run.resolve())
    save(args.output.resolve(), data)
    if args.report:
        args.report.resolve().write_text(report(data))
    print(json.dumps({
        arm["arm"]: arm["summary"]["family_macro"]["top_k"]["10"]
        for arm in data["arms"]
    }, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
