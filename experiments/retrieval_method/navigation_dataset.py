"""校验、版本化冻结双来源问答题集；金标准不传给检索或回答模型。"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import time


INTENTS = {"概念解释", "案例查找", "配置定位", "跨文件关联", "差异比较", "使用条件", "修改导航", "证据追溯"}
SOURCES = {"tutorial": {"tutorial"}, "manual": {"manual"}, "cross": {"tutorial", "manual"}}
QUALITY_RULES = {
    "concept_accuracy": "只计正确定位且语义/作用域正确的目标概念；逐项二元评分，无目标为null。",
    "case_accuracy": "须正确求解器/案例/阶段路径；同名但错误求解器不得分；无案例目标为null。",
    "file_dictionary_accuracy": "须同时匹配原始文件和完整作用域字典路径；脚本导航按文件/命令段评分。",
    "manual_accuracy": "指导书相关金标准逐项0/1/2：错误或缺失/部分正确/完整且有支持；仅案例题为null。",
    "cross_source_completeness": "每个gold要点正确且两来源关联范围成立；完整跨源要点数/所需要点数，仅cross计。",
    "required_evidence_recall": "必要证据单元已见原文覆盖；只覆盖标题不计。冻结逐行严格覆盖下界与经复核等价证据覆盖分开。",
    "citation_accuracy": "引用必须来自该会话已见原文且支持所附主张；路径/行号有效不足以证明支持。",
    "evidence_status_accuracy": "区分手册明确陈述、案例实例、确定对齐、共现、推断、未验证；推荐不可提升为必需。",
    "ambiguity_accuracy": "逐项识别预设冲突/条件范围/未知；不凭空制造歧义；无歧义目标为null。",
    "answer_accuracy": "所有gold要点0/1/2；平均分除2；额外严重错误另记并使成功失败。",
    "qa_success": "全部gold完整有支持，无严重额外错误，无无效或不支持的实质引用，必须证据齐备；布尔。",
    "first_answer_success": "首次实际提交的完整答案按同规则评；本协议每会话只提交一次，故与qa_success相同。不得用首次证据齐备替代。"
}
COST_RULES = {
    "tool_calls": "所有已尝试工具（含失败、图内部自动调用若有）；finish是模型决策，不是工具。",
    "graph_queries": "全部locate/图扩展请求；内部子调用独立计数。",
    "file_search_calls": "普通原文搜索次数；catalog单列且计总工具。",
    "source_read_calls": "显式读取原文次数；图内原文读取操作另列并计入all_source_read_operations。",
    "repeated_search_calls": "同会话相同工具/原查询/作用域/offset的再次调用；query仅空白归一。",
    "failed_tool_calls": "工具错误、无效动作、预算失败分开列出。",
    "transport_attempts": "全部API尝试和重试，失败usage未知时为null，不能当0。",
    "internal_content_characters": "实际被扫描/评分/候选展开/重排/读取的Unicode字符量，重复操作重复计；原始与派生元数据分别记录。不是API计费token。",
    "returned_context_characters": "实际序列化工具返回（含元数据与重复）累计Unicode字符；token若为chars/4必须标为估算。",
    "answer_tokens": "首次/最终回答实际API completion_tokens。",
    "total_model_tokens": "所有成功响应usage.total_tokens，加可得失败usage；未知失败消耗不假定零，不重复加缓存或reasoning字段。",
    "retrieval_seconds": "所有工具实际耗时；图初始化、索引验证/维护单列，不藏入启动外成本。",
    "session_seconds": "含请求、重试、检索、回答的总时长；中断等待另列，断点恢复计已发生尝试。",
    "construction_cost": "图构建/原文读取/抽取/对齐/审核成本与查询分开；记录冷构建、复用、更新及依赖身份。"
}


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha(raw):
    return hashlib.sha256(raw if isinstance(raw, bytes) else raw.encode()).hexdigest()


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    if path.exists() and path.read_text() != content:
        raise ValueError("frozen dataset exists; create a new version: " + str(path))
    if not path.exists():
        path.write_text(content)


def source_kind(path):
    if re.fullmatch(r"manual/markdown/(?:0\d|1\d|20)_[^/]+\.md", path):
        return "manual"
    if path.startswith("tutorials/"):
        return "tutorial"
    raise ValueError("not original user-guide/tutorial evidence: " + path)


def build(authored, corpus, output, manual_origin=None, tutorial_origin=None, revision=None):
    data = json.loads(authored.read_text())
    changes = json.loads(revision.read_text()) if revision else None
    if changes:
        known = {item["id"]: item for item in data["items"]}
        if not changes.get("reason") or not changes.get("version") or not set(changes["patches"]) <= set(known):
            raise ValueError("invalid versioned revision")
        for uid, patch in changes["patches"].items():
            if not set(patch) <= {"questions", "gold", "allowed", "forbidden", "evidence", "ambiguity"}:
                raise ValueError("revision may not silently change split/family/category")
            known[uid].update(patch)
        data["version"] = changes["version"]
        data["revision"] = {"reason": changes["reason"], "parent_authored_sha256": sha(authored.read_bytes()),
                            "revision_sha256": sha(revision.read_bytes()), "evaluation_results_observed": False}
    items = data["items"]
    identifiers = [x["id"] for x in items]
    if len(set(identifiers)) != len(items):
        raise ValueError("duplicate item id")
    all_intents, families, text_seen = set(), {}, set()
    sources = {}
    # Freeze the entire common readable corpus, not just gold evidence files.
    for path in sorted(corpus.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(corpus).as_posix()
        try:
            kind = source_kind(relative)
            raw = path.read_bytes()
            text = raw.decode("utf-8")
        except (ValueError, UnicodeError):
            continue
        if "\x00" in text or path.suffix.lower() in (".stl", ".eps", ".vtk"):
            continue
        origin = ((manual_origin / path.name) if manual_origin and kind == "manual" else
                  (tutorial_origin / relative.removeprefix("tutorials/")) if tutorial_origin and kind == "tutorial" else None)
        origin_hash = sha(origin.read_bytes()) if origin and origin.is_file() else None
        sources[relative] = {"sha256": sha(raw), "characters": len(text), "lines": len(text.splitlines()),
                             "source_kind": kind, "origin_sha256": origin_hash,
                             "origin_matches": origin_hash == sha(raw) if origin_hash else None}
    if any(s["origin_matches"] is False for s in sources.values()):
        raise ValueError("original corpus mismatch; inspect before using it as ground truth")
    questions = {"dev": [], "holdout": []}
    annotations = {"dev": [], "holdout": []}
    for item in items:
        category, split = item["category"], item["split"]
        if split not in questions or category not in SOURCES:
            raise ValueError("invalid split/category")
        if families.setdefault(item["family"], split) != split:
            raise ValueError("fact family leaks across split")
        if not set(item["intents"]) <= INTENTS or not item["intents"]:
            raise ValueError("invalid intent")
        all_intents.update(item["intents"])
        if len(item["questions"]) < 2 or not item["gold"] or not item["allowed"]:
            raise ValueError("missing paraphrases/gold/allowed answers")
        evidence = []
        for index, (path, start, end) in enumerate(item["evidence"], 1):
            metadata = sources[path]
            if not (type(start) is int and type(end) is int and 1 <= start <= end <= metadata["lines"]):
                raise ValueError("invalid evidence range: " + item["id"])
            lines = (corpus / path).read_text().splitlines()
            quote = "\n".join(lines[start - 1:end])
            if not quote.strip():
                raise ValueError("blank evidence")
            evidence.append({"id": f"{item['id']}:e{index}", "path": path, "start": start, "end": end,
                             "source_kind": metadata["source_kind"], "sha256": metadata["sha256"],
                             "quote": quote, "quote_sha256": sha(quote), "pdf_page": None,
                             "status": "manual_explicit" if metadata["source_kind"] == "manual" else "tutorial_observed"})
        if {e["source_kind"] for e in evidence} != SOURCES[category]:
            raise ValueError("wrong required sources: " + item["id"])
        annotation = {k: v for k, v in item.items() if k not in ("questions", "evidence")}
        annotation["evidence"] = evidence
        annotation["required_sources"] = sorted(SOURCES[category])
        annotation["score_rule"] = "navigation-quality-v1"
        annotations[split].append(annotation)
        for index, question in enumerate(item["questions"], 1):
            if question in text_seen:
                raise ValueError("duplicate question")
            text_seen.add(question)
            questions[split].append({"id": f"{item['id']}-p{index}", "item_id": item["id"], "question": question})
    overlaps = []
    for dev in annotations["dev"]:
        for hold in annotations["holdout"]:
            for a in dev["evidence"]:
                for b in hold["evidence"]:
                    if a["path"] == b["path"] and max(a["start"], b["start"]) <= min(a["end"], b["end"]):
                        overlaps.append([dev["id"], hold["id"], a["path"]])
    if overlaps:
        raise ValueError("cross-split evidence overlap: " + encoded(overlaps))
    if all_intents != INTENTS:
        raise ValueError("missing query intents")
    for split in questions:
        if {a["category"] for a in annotations[split]} != set(SOURCES):
            raise ValueError("split lacks a source category")
        save(output / f"{split}.questions.json", questions[split])
        save(output / f"{split}.annotations.json", annotations[split])
    save(output / "authored_snapshot.json", data)
    save(output / "corpus-manifest.json", sources)
    save(output / "scoring-rules.json", {"version": "navigation-quality-v1", "quality": QUALITY_RULES,
         "cost": COST_RULES, "aggregation": "三类单列/宏平均/总体；质量不劣后再比较全量及配对共同成功成本；失败题不能删除。",
         "semantic_review": "先冻结金标准，输出逐项理由和所支持原文。自动评审为候选，需审阅，不把关键词/覆盖当答案正确。",
         "holdout": "实现、图、提示、预算、题目、评分器冻结后才运行；看过结果不得改当前题/评分抬分。"})
    summary = {"version": data["version"], "authorship": data["authorship"],
        "authored_sha256": sha(encoded(data)), "compiler_sha256": sha(Path(__file__).read_bytes()),
        "families": families, "counts": {split: {"items": len(annotations[split]), "questions": len(questions[split]),
            "categories": dict(Counter(a["category"] for a in annotations[split]))} for split in questions},
        "source_files": len(sources), "source_characters": sum(s["characters"] for s in sources.values()),
        "source_kinds": dict(Counter(s["source_kind"] for s in sources.values())),
        "all_sources_match_originals": all(s["origin_matches"] is True for s in sources.values()),
        "cross_split_evidence_overlaps": overlaps,
        "split_review": "作者逐家族划分；所有跨split必要证据区间不重叠。不是独立作者盲审，也不声称语义自动审计完备。",
        "manual_origin": str(manual_origin) if manual_origin else None,
        "tutorial_origin": str(tutorial_origin) if tutorial_origin else None,
        "excluded": "作者98_reviewed_defaults、solver source、PDF/二进制/几何数据；图和评测注释不进入原文工具。",
        "artifacts": {p.name: sha(p.read_bytes()) for p in sorted(output.glob("*.json")) if p.name != "manifest.json"}}
    save(output / "manifest.json", summary)
    print(encoded({k: v for k, v in summary.items() if k not in ("families", "artifacts")}))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--authored", type=Path, required=True)
    p.add_argument("--corpus", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--manual-origin", type=Path)
    p.add_argument("--tutorial-origin", type=Path)
    p.add_argument("--revision", type=Path)
    a = p.parse_args()
    build(a.authored, a.corpus, a.output, a.manual_origin, a.tutorial_origin, a.revision)
