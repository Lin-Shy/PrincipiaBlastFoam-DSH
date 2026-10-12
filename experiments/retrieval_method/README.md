# 第2章检索实现与评测

新协议维护入口为[基础agent检索增强实验](AUGMENTATION_PLAN.md)：四组共同保留grep、定位与原文读取，分别新增BM25、E5或图谱，使用用户授权qwen_proxy。归档`grep_augmentation_v4/`的正式8B作答、证据/资源/消融及原评分网格完成，正文和正式图件已同步；原8B评分失败保留未知，后注册14B裁判及同请求网络恢复完成；419全项有效/171部分无效/291输出失败/271空答案。旧`aliyun_8b_cross_source_v1/`保持历史冻结身份，完整回答图谱[14.24,15.28]%/基础1.04%，格式未知保留，主检验不宣布显著优越。

本目录维护算法、评测适配器和审计脚本。实验唯一归档为 `../../../graduation-experiment-results/chapter2_retrieval/`，统一题集为其 `datasets/natural_navigation_qa/`。当前检索增强为`grep_augmentation_v4/`，正式证据/资源结果已同步论文，后注册14B裁判评分及网络恢复完成，修订报告与严格一致性审计独立归档；`aliyun_8b_cross_source_v1/`是历史冻结证据。取材从归档 `论文取材入口.md` 开始。

研究问题、论证主线与方法边界见[第2章共享设计](../../../graduation-research/chapters/chapter02.md)。本目录维护具体实现与验证，冻结协议和证据继续由实验归档保存。

## 当前正式实现

- `chapter2_graph_retriever.py`：免外部索引图检索与结构化原文回读。
- `chapter2_canonical_delivery.py`：权威证据映射、去重、原生排名与实际字符预算。
- `chapter2_role_graph.py`：角色增强和跨来源关系。
- `chapter2_common_planner.py`、`chapter2_cited_answer.py`：轻量模型公共规划和带引用回答。
- `chapter2_formal_*`：正式输入、实现冻结、执行和评分；现有冻结运行自带 runtime 快照。

离线构图/语义校验使用 `deepseek-flash`，在线过程按轻量模型协议，最新为 `qwen3-8b`。留出集不锁定，gold 仅由评测侧读取。自研链路只持久化图与构图清单；E5/BM25是隔离对照，不进入自研最终方法。

历史 `candidate_qa.py` 的二阶段默认替换、旧轮次和 post-hoc 指标只解释当时开发实验，不作为当前正式结果入口或新实验停止条件。历史冻结源码/回答/评分不改；当前源文件的更改不等于重新生成冻结结果。

论文仅在 `../../../graduation-manuscript/` 以 LaTeX 维护；最终图件与 CSV 位于该项目 `assets/chapter2/`。制图脚本在 `../../../graduation-visualization/`。

## 历史本地人工评分（新协议不使用）

`chapter2_human_rating.py` 生成48份冻结回答的离线HTML，支持事实/引用两项五分制、选填备注、缓存续审、JSON/CSV导出及封存后解盲。用法与新增量表协议见 [human_rating_README.md](human_rating_README.md)。原二元盲审脚本和冻结评分保持原样；此入口不调用模型，不自动生成真人判断。
