"""Dense-only E5 comparison using frozen raw-corpus passages as evidence."""
from __future__ import annotations

from collections import Counter
from pathlib import Path
import time

import candidate_hybrid as hybrid
import candidate_qa as candidate
import graphify_qa as base
import navigation_qa as qa


def prompt(options):
    result = qa.COMMON.replace("最多8次决策", "最多8次模型决策")
    result += (
        '附加工具locate: {action:"locate",translation:"可选忠实英文翻译",'
        'query:"本轮需补充的材料",needs:["尚缺的答案槽位"],reason:"理由"}。'
        "locate仅用冻结的多语种E5向量在原文passage中做稠密召回，直接返回带逐行行号的原文；"
        "不使用知识图谱、BM25、字面精确匹配、题库或gold。第一步优先locate。"
        "若问题出现案例名、求解器名、文件名或配置标识符，translation和query必须原样保留；"
        "每轮在needs中明确尚缺的对象、条件、值或来源侧，不要重复已经完整支持的内容。\n"
    )
    result += (
        "其中最多6次用于探索，保留2次模型决策给主张计划和草稿的语义核验。"
        "最终草稿最多2400输出token，只有已读引用及语义核验均通过的主张才会原样提交。"
        "原文返回预算预留800字符用于程序引用检查，总额仍为24000。\n"
    )
    return result


class Session(candidate.NumberedSession):
    def __init__(self, engine, method, question):
        super().__init__(engine, method, question)
        self.options = engine.options
        self.needs = []
        self.seen_passages = set()

    def restore(self, action, result):
        self.observe(result)
        self.seen_requests.add(qa.wire({k: v for k, v in action.items() if k != "reason"}))
        if isinstance(action.get("needs"), list):
            self.needs = list(action["needs"])
        for item in result.get("items", []):
            passage_id = item.get("passage_id") if isinstance(item, dict) else None
            if isinstance(passage_id, str):
                self.seen_passages.add(passage_id)

    def dispatch(self, action, cap):
        if action.get("action") != "locate":
            return super().dispatch(action, cap)
        begin = time.monotonic()
        identity = qa.wire({k: v for k, v in action.items() if k != "reason"})
        repeat = identity in self.seen_requests
        self.seen_requests.add(identity)
        self.calls["locate"] += 1
        try:
            translation = action.get("translation", "")
            gap = action.get("query", "")
            needs = action.get("needs", [])
            if (not isinstance(translation, str) or not isinstance(gap, str)
                    or not isinstance(needs, list) or len(needs) > 8
                    or any(not isinstance(value, str) or len(value) > 120 for value in needs)):
                raise ValueError("invalid translation/query/needs")
            self.needs = list(needs)
            query = "\n".join(value for value in (
                self.question, translation, gap, "\n".join(needs)
            ) if value)
            passages, retrieval = self.e.retriever.query(
                query, limit=32, seen_ids=self.seen_passages, mode="vector"
            )
            result = {"status": "ok", "items": [], "next_offset": None,
                      "retrieval_mode": "dense_vector_only"}
            for index, passage in enumerate(passages):
                item = {**self.source_item(passage["path"], passage["start"], passage["end"]),
                        "passage_id": passage["id"]}
                proposed = {**result, "items": result["items"] + [item],
                            "next_offset": index + 1 if index + 1 < len(passages) else None}
                if len(qa.wire(proposed)) > cap:
                    result["next_offset"] = index
                    if not result["items"]:
                        result["status"] = "item_exceeds_budget"
                    break
                result = proposed
            self.restore(action, result)
            accounting = {
                "seconds": time.monotonic() - begin,
                "repeat": repeat,
                "content": retrieval["work"],
                "retrieval_audit": retrieval,
                "initialization": None,
                "initialization_time_included": False,
                "actual_graph_loaded": False,
            }
            return result, accounting
        except (ValueError, TypeError, KeyError) as error:
            result = {"status": "tool_error", "reason": str(error)[:160]}
            return result, {
                "seconds": time.monotonic() - begin, "repeat": repeat,
                "content": {}, "retrieval_audit": None, "initialization": None,
                "initialization_time_included": False, "actual_graph_loaded": False,
            }


class Engine(base.Engine):
    def __init__(self, run, variant, index, options=None):
        super().__init__(run, variant)
        self.options = {**candidate.DEFAULTS, **(options or {}), "navigation_only": False}
        self.graph_path = None
        self.retriever = hybrid.Retriever(Path(index), semantic=True)
        self.session_type = Session
        self.prompt_function = prompt


def run_one(engine, question, method, key, replicate=1, replay=False):
    return candidate.run_one(engine, question, method, key, replicate, replay)
