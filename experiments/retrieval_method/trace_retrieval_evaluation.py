"""从冻结开发集会话补算“实际送达原文”的探索性检索指标。

这不是单轮后端检索榜：会话中的查询由回答模型多轮自适应选择。产物必须始终
标为 trace-evidence-delivery，不能替代预注册的端到端门禁或解锁留出集。
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import canonical_evidence_v1 as canonical


LABELS = {
    "control": "无图",
    "native": "Graphify native",
    "text_adapter": "Graphify text-adapter",
    "principia_index_free": "Principia 候选010",
}


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


class Corpus:
    def __init__(self, arm_root):
        self.root = arm_root / "skill" / "corpus"
        self.manifest = read(arm_root / "corpus-manifest.json")
        self.cache = {}

    def lines(self, path):
        if path not in self.manifest:
            raise ValueError("trace returned a path outside the frozen corpus: " + path)
        if path not in self.cache:
            source = self.root / path
            if sha(source) != self.manifest[path]["sha256"]:
                raise ValueError("frozen corpus source changed: " + path)
            self.cache[path] = source.read_text().splitlines()
        return self.cache[path]

    def characters(self, path, start, end):
        lines = self.lines(path)
        if not 1 <= start <= end <= len(lines):
            raise ValueError("trace evidence range outside frozen source")
        return len("\n".join(lines[start - 1:end]))


def source_kind(path):
    if path.startswith("manual/"):
        return "manual"
    if path.startswith("tutorials/"):
        return "tutorial"
    return "other"


def case_id(path, cases):
    return next((case for case in cases if f"tutorials/{case}/" in path), None)


def event_ranges(result):
    """Yield exact original ranges in their native within-event order."""
    for collection in (result.get("items", []), result.get("locations", [])):
        if isinstance(collection, list):
            for item in collection:
                if isinstance(item, dict):
                    yield item
    evidence = result.get("evidence")
    sources = result.get("sources", {})
    if isinstance(evidence, dict) and isinstance(sources, dict):
        for evidence_id, item in evidence.items():
            if not isinstance(item, dict) or item.get("source") not in sources:
                continue
            yield {**item, "path": sources[item["source"]], "evidence_id": evidence_id}


def extract_units(result, corpus, annotation):
    units = []
    cumulative_characters = 0
    cumulative_seconds = 0.0
    native_rank = 0
    for event_index, event in enumerate(result.get("events", [])):
        returned = event.get("returned_characters", 0)
        if type(returned) is not int or returned < 0:
            raise ValueError("invalid trace returned-character accounting")
        cumulative_characters += returned
        accounting = event.get("accounting", {})
        seconds = accounting.get("seconds", 0) if isinstance(accounting, dict) else 0
        if not isinstance(seconds, (int, float)) or seconds < 0:
            raise ValueError("invalid trace latency accounting")
        cumulative_seconds += seconds
        payload = event.get("result")
        if not isinstance(payload, dict):
            continue
        for within_event_rank, item in enumerate(event_ranges(payload), 1):
            path, start, end = item.get("path"), item.get("start"), item.get("end")
            if not isinstance(path, str) or type(start) is not int or type(end) is not int:
                continue
            native_rank += 1
            units.append(canonical.canonical_unit(
                path=path,
                start=start,
                end=end,
                source_sha256=corpus.manifest[path]["sha256"],
                source_kind=source_kind(path),
                native_unit={
                    "action": event.get("action", {}).get("action"),
                    "event_index": event_index,
                    "within_event_rank": within_event_rank,
                    "evidence_id": item.get("evidence_id"),
                },
                native_rank=native_rank,
                query_step=event.get("step", event_index),
                source_characters=corpus.characters(path, start, end),
                cumulative_returned_characters=cumulative_characters,
                cumulative_query_seconds=cumulative_seconds,
                case_id=case_id(path, annotation.get("cases", [])),
                scope_id=None,
            ))
    return units


def trace_totals(result):
    returned = 0
    seconds = 0.0
    for event in result.get("events", []):
        characters = event.get("returned_characters", 0)
        accounting = event.get("accounting", {})
        duration = accounting.get("seconds", 0) if isinstance(accounting, dict) else 0
        if type(characters) is not int or characters < 0:
            raise ValueError("invalid trace returned-character accounting")
        if not isinstance(duration, (int, float)) or duration < 0:
            raise ValueError("invalid trace latency accounting")
        returned += characters
        seconds += duration
    declared = result.get("returned_characters", returned)
    if type(declared) is not int or declared < returned:
        raise ValueError("invalid declared session returned-character total")
    # Candidate 010 also charges a deterministic citation-check packet to its
    # session budget.  It is not retrieved corpus evidence, so keep it visible
    # but exclude it from evidence-retrieval character curves.
    return returned, seconds, declared


def evaluate(run):
    protocol = read(run / "protocol.json")
    if protocol.get("holdout_unlocked") is not False:
        raise ValueError("trace evaluation requires the development-only locked protocol")
    rows_by_arm = {}
    annotation_hashes = {}
    for arm, methods in protocol["groups"].items():
        if len(methods) != 1:
            raise ValueError("trace evaluator expects one method per arm")
        method = methods[0]
        arm_root = run / arm
        corpus = Corpus(arm_root)
        annotations = {row["id"]: row for row in read(
            arm_root / "evaluation_only" / "annotations.json")}
        annotation_hashes[arm] = sha(arm_root / "evaluation_only" / "annotations.json")
        questions = read(arm_root / "questions.json")
        rows = []
        for question in questions:
            annotation = annotations[question["item_id"]]
            for replicate in range(1, protocol["replicates"] + 1):
                session = f"{question['id']}--{method}--r{replicate}"
                result_path = arm_root / "sessions" / session / "result.json"
                if not result_path.exists():
                    raise ValueError("missing frozen result: " + arm + "/" + session)
                result = read(result_path)
                identity = (result["id"], result["item_id"], result["method"], result["replicate"])
                expected = (question["id"], question["item_id"], method, replicate)
                if identity != expected:
                    raise ValueError("frozen result identity mismatch")
                units = extract_units(result, corpus, annotation)
                returned_characters, query_seconds, declared_characters = trace_totals(result)
                metrics = canonical.score(annotation["evidence"], units)
                metrics["returned_characters"] = returned_characters
                metrics["query_seconds"] = query_seconds
                metrics["session_declared_returned_characters"] = declared_characters
                metrics["non_retrieval_check_characters"] = declared_characters - returned_characters
                rows.append({
                    "arm": arm,
                    "method": method,
                    "session": session,
                    "question_id": question["id"],
                    "family": question["item_id"],
                    "category": annotation["category"],
                    "result_sha256": sha(result_path),
                    "canonical_units": canonical.deduplicate(units),
                    "metrics": metrics,
                })
        rows_by_arm[arm] = {
            "arm": arm,
            "method": method,
            "rows": rows,
            "summary": canonical.aggregate(rows),
        }
    return {
        "schema": "trace-evidence-delivery-retrieval-evaluation-v1",
        "status": "post-hoc exploratory development-set analysis",
        "scope": "exact authoritative source ranges actually delivered during frozen multi-step answer sessions",
        "not_claimed": [
            "not a single-call backend retrieval leaderboard",
            "not a replacement for the preregistered answer-quality gate",
            "does not unlock holdout evaluation",
            "precision is a required-gold-only lower bound because relevance labels are not exhaustive",
        ],
        "run_protocol_sha256": sha(run / "protocol.json"),
        "implementation_sha256": {
            "trace_retrieval_evaluation.py": sha(Path(__file__)),
            "canonical_evidence_v1.py": sha(Path(canonical.__file__)),
        },
        "gold_annotations_sha256": annotation_hashes,
        "holdout_unlocked": False,
        "ks": list(canonical.DEFAULT_K),
        "returned_character_budgets": list(canonical.DEFAULT_BUDGETS),
        "arms": list(rows_by_arm.values()),
    }


def percent(value):
    return f"{100 * value:.2f}%"


def report(data):
    lines = [
        "# 第5轮冻结轨迹的补充性检索质量分析",
        "",
        "> 本报告是开发集上的 post-hoc 探索性分析，评价冻结多步会话中实际送达回答模型的权威原文。它不是单轮检索器排行榜，不替代原预注册门禁，也不解锁保留集。",
        "",
        "## 主要结果（事实族宏平均）",
        "",
        "| 方法 | Recall@5 | Recall@10 | Complete@10 | Hit@10 | MRR | nDCG@10 | Precision@10* |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for arm in data["arms"]:
        summary = arm["summary"]["family_macro"]
        k5, k10 = summary["top_k"]["5"], summary["top_k"]["10"]
        lines.append("| " + " | ".join([
            LABELS.get(arm["arm"], arm["arm"]), percent(k5["recall"]), percent(k10["recall"]),
            percent(k10["complete_evidence_set_success"]), percent(k10["hit_rate"]),
            f"{summary['mrr']:.3f}", f"{k10['ndcg']:.3f}",
            percent(k10["precision"]),
        ]) + " |")
    lines += [
        "",
        "\\* Precision只把冻结的必需gold证据视为相关，未穷尽标注的有用辅助证据会被计为非相关，因此只能解释为下界。",
        "",
        "## 返回字符预算",
        "",
        "| 方法 | Recall@6k字符 | Recall@12k字符 | Recall@24k字符 | Complete@24k字符 | 平均实际送达字符 |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for arm in data["arms"]:
        summary = arm["summary"]["family_macro"]
        budgets = summary["by_returned_character_budget"]
        lines.append("| " + " | ".join([
            LABELS.get(arm["arm"], arm["arm"]), percent(budgets["6000"]["recall"]),
            percent(budgets["12000"]["recall"]), percent(budgets["24000"]["recall"]),
            percent(budgets["24000"]["complete_evidence_set_success"]),
            f"{summary['returned_characters']:,.0f}",
        ]) + " |")
    lines += [
        "",
        "## 解释边界",
        "",
        "- K按去重后首次出现的精确原文行段计算；相同路径、哈希和行段重复返回只记第一次。",
        "- Recall要求冻结gold证据原子被一个或多个返回范围完整覆盖；Hit只要求至少有一个返回范围与gold相交。",
        "- nDCG相关性等级固定为：单个返回范围完整包含至少一个gold原子记2，只有部分行重叠记1，否则记0；完整多证据召回仍由Recall和Complete单独衡量。",
        "- 字符预算只累计检索工具返回的上下文；候选010内部确定性引用检查包单列审计，不冒充检索证据字符。",
        "- Graphify导航节点本身不是权威原文，只有后续实际读取的原始文件行进入本报告；这评价的是端到端证据送达，而不是Graphify原生节点排序。",
        "- 公平的单轮检索器比较仍需各后端输出原生排名并映射到同一证据层；不得直接比较chunk、Graphify节点和自研图节点的原生K值。",
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
    compact = {
        arm["arm"]: arm["summary"]["family_macro"]["top_k"]["10"]
        for arm in data["arms"]
    }
    print(json.dumps(compact, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
