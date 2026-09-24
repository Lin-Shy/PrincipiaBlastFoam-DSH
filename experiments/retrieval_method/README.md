# 第2章检索实验代码

论文数据、冻结结果与取材说明统一位于 `graduation-experiment-results/chapter2_retrieval/`，从该目录的 `论文取材入口.md` 开始。此目录保存实现和评测脚本，不是实验结果归档。2026-09-23 已按用户要求删除旧轮次及淘汰方案的原始运行目录；`最新进展.md` 和 `历史实验简表.md` 保留简要结果与原哈希，旧运行不可再逐项重放。

## 当前自研方法

- `index_free_graph_evidence.py`：查询时扫描已持久化图的节点、边、标签、角色、作用域和来源路径，返回候选与遍历信息；不建立 E5、BM25、向量、倒排或预计算 passage 索引。
- `candidate_qa.py`：默认使用 `navigation_only=true`、`source_context_lines=16`。模型先看图导航卡片，再选原始来源并由 `read_sources` 读取权威原文；所选范围可向前后扩展最多 16 行，同文件重叠范围合并，引用仍须指向实际支持主张的精确行。原候选 010 证据直出可显式设 `navigation_only=false`。
- `export_runtime_graph.py`：从完整图导出只含必要运行字段的图副本，不删节点、不改边、不建立外部检索索引。

当前默认方法是第五轮正式门禁之后单独标注的 post-hoc 开发集选择结果。原第五轮预注册总门禁失败，保留集仍锁定；不得把当前默认替换写成原门禁通过或保留集验证。

## 比较、评分与复核

- `graphify_qa.py`、`graphify_query_backend.py`：Graphify 基线查询与问答；`.txt` 适配仅供 Graphify 摄取，输出必须映射回原路径。
- `retrieval_leaderboard.py`、`navigation_catalogue_evaluation.py`、`vector_comparator_evaluation.py`：正式第五轮及补充对照的运行入口。保留的冻结运行目录自带对应代码快照。
- `leaderboard_admission.py`、`leaderboard_review.py`、`leaderboard_adjudication.py`、`leaderboard_results.py`：预算/模型身份准入、来源审阅、裁决和质量汇总。
- `canonical_evidence_v1.py`、`trace_retrieval_evaluation.py`、`first_call_file_retrieval.py`：补充性证据层和检索分析。冻结会话的首次调用只能称为 `whole-system first-call`，多步轨迹只能称为实际证据送达质量。

最终论文图件位于 `graduation-visualization/chapter_02_knowledge_graph_retrieval/`：方法框架图用 imagegen 生成，实测比较图从冻结质量 JSON 绘制。
