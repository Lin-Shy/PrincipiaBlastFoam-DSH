"""Render a provenance-linked Chapter 2 v7r1 results report."""
import argparse
import hashlib
import json
from pathlib import Path


ARMS = ("control", "native", "text_adapter", "principia_index_free", "vector_e5_dense")
LABELS = {"control": "无图原文检索", "native": "Graphify 原生摄取",
          "text_adapter": "Graphify 文本适配", "principia_index_free": "自研二阶段图方法",
          "vector_e5_dense": "E5 向量对照"}


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def percentage(value):
    return f"{100*value:.2f}%"


def stage(value):
    if value.get("not_applicable"):
        return "不适用"
    if not value.get("completed_samples"):
        return "未测得（n=0）"
    return f"{value['median_seconds']:.2f} / {value['p95_seconds']:.2f}（n={value['completed_samples']}）"


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dev-quality", type=Path, required=True)
    p.add_argument("--holdout-quality", type=Path, required=True)
    p.add_argument("--performance", type=Path, required=True)
    p.add_argument("--construction-accounting", type=Path, required=True)
    p.add_argument("--dataset", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    dev, holdout, timing, construction = (read(x) for x in
        (a.dev_quality, a.holdout_quality, a.performance, a.construction_accounting))
    if (dev["split"], holdout["split"], timing["mode"]) != ("dev", "holdout", "sequential_performance"):
        raise ValueError("report input scope mismatch")
    if dev["dataset_manifest_sha256"] != holdout["dataset_manifest_sha256"] != sha(a.dataset / "manifest.json"):
        raise ValueError("dataset manifest mismatch")
    if holdout["families"] != 40 or holdout["questions"] != 240 or holdout["replicates"] != 3:
        raise ValueError("holdout denominator mismatch")
    rows = ["# 第2章新版自然问答评测 v7r1：20/80 最终报告", "",
            "本报告只使用新版 50 个事实族、300 道题的冻结输入。旧版 v5 的开发探索和五轮门槛结论独立保留，不并入本表分母。",
            "", "## 输入与统计", "",
            f"- 题集 manifest SHA-256：`{holdout['dataset_manifest_sha256']}`；原始语料 702 个可读权威文本文件。",
            "- 开发：10 族、60 题，每方法 1 次；留出：40 族、240 题，每方法 3 次，计划每方法 720 次。",
            "- 六种同族问法及重复先求平均，再对事实族宏平均；差异以同族配对、固定种子 20260928 的 10000 次 bootstrap 给出 95% 百分位区间。",
            "- 审阅为方法盲化的两次独立 deepseek-flash 调用，分歧第三次裁决；与回答模型同族。未取得有效评分的会话保守计作失败，具体数量单列。",
            "", "## 整题质量", "",
            "| 方法 | 开发严格成功 / 计划 | 留出严格成功 / 计划 | 留出完整回答 | 留出有效盲审 | 留出无有效评分 |",
            "|---|---:|---:|---:|---:|---:|"]
    for arm in ARMS:
        d, h = dev["methods"][arm], holdout["methods"][arm]
        rows.append(f"| {LABELS[arm]} | {d['strict_successes']}/{d['planned_sessions']} ({percentage(d['strict_success_planned_denominator'])}) | "
                    f"{h['strict_successes']}/{h['planned_sessions']} ({percentage(h['strict_success_planned_denominator'])}) | "
                    f"{h['complete_answers']} | {h['reviewed_sessions']} | {h['unresolved_reviews']} |")
    rows.extend(["", "以自研方法减去同族对照方法的严格成功率：", "",
                 "| 对照方法 | 差值 | 95% CI | 配对事实族 |", "|---|---:|---:|---:|"])
    for arm in ("control", "native", "text_adapter", "vector_e5_dense"):
        x = holdout["paired_differences"]["principia_minus_" + arm]
        rows.append(f"| {LABELS[arm]} | {x['difference']*100:+.2f} pp | "
                    f"[{x['lower_95']*100:+.2f}, {x['upper_95']*100:+.2f}] pp | {x['families']} |")
    sample = timing.get("performance_sample")
    scope = (f"从开发集固定抽取 {sample['planned_per_method']} 题（教程、手册、跨来源各 2 族），每方法 1 次"
             if sample else "以新版开发集 60 题每方法 1 次")
    rows.extend(["", "## 顺序性能与分段耗时", "",
                 f"同机、固定并发度 1，{scope}按方法顺序测量。表内为中位数 / P95（秒），括号内为该阶段实际有效样本数；加载和冷构建是运行级观测。并行质量会话的时延另保留逐题原始记录，不作为此表性能基准。",
                 "", "| 方法 | 完成/计划 | 冷构建 | 加载 | 搜索 | 回答 | 端到端 | 重试事件 |",
                 "|---|---:|---:|---:|---:|---:|---:|---:|"])
    for arm in ARMS:
        t = timing["methods"][arm]
        rows.append(f"| {LABELS[arm]} | {t['completed_questions']}/{t['attempted_questions']} | "
                    f"{stage(t['build'])} | {stage(t['load'])} | {stage(t['search'])} | "
                    f"{stage(t['answer'])} | {stage(t['end_to_end'])} | {t['retry_events']} |")
    rows.extend(["", "构建从首次读取原始语料至图或索引持久化；加载从进程启动至可查询；搜索从工具调用至证据返回，含原文回读；回答为模型请求及重试累计墙钟时间；端到端从接题至最终答案或终止。阶段间还有等待与调度，故各段之和不要求等于端到端。无图索引构建为不适用。",
                 "", "已有构建记录仅包含 Graphify 的多个活跃阶段耗时之和、自研图的确定性结构与关系阶段，以及 E5 嵌入计算阶段。它们都不是完整、同机、从首次语料读取到最终产物持久化的冷构建观测，因此主表未用这些片段冒充完整构建耗时。可追溯片段见 `available_construction_accounting_v7r1.json`。",
                 "", "## 内部限制与可追溯性", "",
                 "五组是完整系统对照，提示词和回答核验流程也有差别，不能仅由系统差异推断检索模块的单独因果效应。题族数量有限，审阅模型与回答模型同族，且失效审阅在各方法间可能不均衡。",
                 "", "内部保留历史开发暴露分层，不据留出结果调整本版本：", "",
                 "| 内部分层 | 事实族数 | 自研严格成功率 |", "|---|---:|---:|"])
    for key, value in holdout.get("internal_exposure_strata", {}).items():
        rate = value["methods"]["principia_index_free"]
        rows.append(f"| `{key}` | {value['families']} | {percentage(rate) if rate is not None else '不适用'} |")
    if sample:
        rows.extend(["", "性能抽样为用户要求缩减后的协议修订。此前全开发集顺序运行在无图臂完成 46 题时中止；本表只取其中固定的 6 题，与其他四臂的相同 6 题对应。进程启动至可查询时间由各臂另一次同机加载测量，不摊入逐题查询。六题 P95 仅为样本描述，不作总体尾延迟推断。"])
    rows.extend(["", "源文件哈希：", "",
                 f"- 开发质量：`{sha(a.dev_quality)}`",
                 f"- 留出质量：`{sha(a.holdout_quality)}`",
                 f"- 顺序性能：`{sha(a.performance)}`",
                 f"- 构建片段：`{sha(a.construction_accounting)}`",
                 "- 逐题回答、模型请求与重试、匿名审阅、逐题计时 JSONL 均保留在 `evaluations/` 对应冻结运行目录。", ""])
    if a.output.exists():
        raise FileExistsError(a.output)
    a.output.write_text("\n".join(rows))
    print(a.output)


if __name__ == "__main__":
    main()
