# 第2章问答评测

当前只评测“问题 → 只读检索 → 回答”。建算例、修改配置及求解器执行的评测入口和运行结果已清除。

双来源任务导航的新入口是 `navigation_qa.py`，题集与冻结运行保存在外部 `chapter2_retrieval/task_navigation_v1/`。它统一比较教程、指导书和跨来源问题，无图组仅使用普通原文文件搜索/读取，可选图和优先图组增加定位工具。当前为开发实验，不预设图谱收益；留出集须在实现冻结后运行。

历史手册主入口是 `evaluate_manual_agent.py`。模型只能调用 `search`、`catalog`、`read`，含图组另有 `neighbors` 和 `relations`；`finish` 结束检索并生成回答。工具分发器没有案例写入、终端执行或求解器接口。问题中可以讨论模型、参数和配置依赖，但交付物是带原文引用的回答。

现有主题集位于外部 `graduation-experiment-results/chapter2_retrieval/manual_agent_latest/`，包含24道题及关键词、章节结构、语义关系三组问答。评测实现和题集快照已经具备，无需部署仿真环境。56题单次检索结果位于 `manual_graph_latest/`，分开统计。

## 检查现有问答

从本项目根目录运行；重放使用已保存响应，不调用模型 API：

```bash
.venv/bin/python experiments/retrieval_method/evaluate_manual_agent.py verify \
  --run ../graduation-experiment-results/chapter2_retrieval/manual_agent_latest \
  --source ../graduation-experiment-results/chapter2_retrieval/manual_agent_latest/source
```

`source/` 包含与该题集冻结清单逐文件哈希一致的原文。后续新增的资料不会进入旧题集重放。`prepare` 校验并冻结问答输入；`run` 通过显式 `--key-file` 使用模型；`verify` 重放已有轨迹；`summarize` 汇总结果。新一轮使用新的外部结果目录并准备 `questions.json`、独立的 `annotations.json`、图文件与实现快照，不能覆盖已完成的问答响应。

## 评分

- **回答质量**：对照原文逐项检查正确性、完整性及条件范围，不用关键词命中或证据覆盖代替答对。
- **引用可靠性**：引用必须是当前会话实际读到且能支撑相应主张的原文。
- **检索成本**：全部检索和阅读调用、累计返回字符、模型用量与耗时。服务失败中未报告的用量记为未知。

比较时固定题目、可读取原文、模型和预算。图谱采用率只解释工具使用情况；当前结果尚未证明图关系能稳定提高答案质量并降低成本。

## 双来源实验的冻结与计量

`freeze_navigation_baseline.py` 保留当前脏工作树白名单快照与实际图身份；`navigation_dataset.py` 校验并冻结三类题、改写、按事实家族划分的开发/留出集和独立金标准。当前题集60条输入，v1及运行前修订v1.1均保留。原指导书以21份Markdown为准，作者总结和求解器源码不混入指导书类别。

`navigation_qa.py prepare` 将代码、图构建输入、题目、评分规则和 `navigation_metrics.py` 固定到新的运行目录；实际问答与离线重放必须使用目录内的 `runner.py`。每步工具输出和API尝试立即保存，断点恢复只补相同请求的传输失败，已成功的工具不重复执行。`metrics.py` 统计内部读文件、分词、候选、序列化、返回上下文、累计API用量及耗时。未知失败usage保留为未知。原文覆盖/引用范围检查不能替代逐项答案审阅。

构建消融由 `build_navigation_construction_ablation.py` 接受冻结skill与候选构建器；它不接收题目或答案。首项开关是 `--parse-included-dictionaries`，沿原始字典的本地literal include发现无文件头的字典片段；物理来源路径与include的有效作用域分开，环境变量/全局include/运行时覆盖仍需进一步核对。关闭/打开开关的语料和构建器相同，不能把新增节点数当问答成功。

`--prepared-skill` 可以把已构建变体原样复制到新问答目录，保留开关对应的图身份，不在准备过程中重新按默认开关构建。`navigation_probe.py` 在相同开发问题或已保存定位动作上做离线结构消融；`compare_navigation_probes.py` 比较除图身份外的完整返回和内部工作量。离线探针不是新一轮真实问答，不能替代三组agent对照。

`navigation_review.py` 生成包含金标准、已见原文、原始引用和回答身份的审阅包，再将显式逐项判定编译为冻结评分器接受的格式。模板只是复用审阅者已经确定的相同判定；编译器不根据关键词或覆盖率决定答案正确性。每项判定和引用审阅保留理由，完全正确的要点必须有会话已见原文支持。

`.dsh/skills/blastfoam-knowledge/scripts/manual_parameters.py` 是下一项独立构建组件，用参数表的章节归属组织原文行、单位、默认子句和条件；公式符号规范化只产生拼写候选，不自动升级为配置键或跨来源确定性边。`freeze_manual_parameters.py` 冻结它的依赖代码、原文身份、逐行核验及构建读操作成本；目前尚未接入问答图谱。

## 统一总榜、消融与留出门控

`retrieval_leaderboard.py` 在相同语料、题集、模型、重复数和公共预算下运行无图、Graphify、GN、GH及证据搜索配置。`candidate_qa.py` 实现完整候选的混合召回、约束路径、证据组、缺口策略和主张核验；`candidate_ablation.py` 物理移除七个单组件及两个预注册交互组合对应的信息或行为。`leaderboard_admission.py` 要求完整网格、供应商模型身份、预算以及每个成功回答生成后的零模型重放；来源审阅未完成时质量保持空值。

`final_method_selection.py` 只在开发集基线、候选和全部消融均准入后执行预注册选择规则，并生成实现门。`final_holdout.py` 验证该门、源运行协议和未打开题集的冻结哈希后，才将留出问题复制进隔离运行；基线与候选分别使用各自冻结运行时，避免模块版本交叉。`final_evaluation_gate.py` 串联回答、重放、盲化来源审阅、纠正仲裁、质量汇总及完整成本账本。`final_holdout_results.py` 生成独立留出榜，不把开发分数混入留出结论。

供应商网络错误按冻结重试上限处理。`ablation_operational_sensitivity.py` 另行给出终止传输失败的反事实边界，只用于检查服务扰动，不覆盖预注册主分析或重写失败分数。

## v5 补充性检索质量指标

`canonical_evidence_v1.py` 定义统一权威证据行段、首次出现去重以及 Recall@K、Hit Rate@K、MRR、nDCG@K、必要 gold Precision@K 下界、完整证据集成功率和返回字符预算指标。不同后端的 chunk、文件、Graphify 节点和自研图节点不能直接横向比较，必须先保留原生排名并映射到该统一证据层。

`trace_retrieval_evaluation.py` 可在不调用模型的情况下读取冻结 v5 开发集结果，评价多步问答轨迹中实际送达模型的原始证据。例如：

```bash
.venv/bin/python experiments/retrieval_method/trace_retrieval_evaluation.py \
  --run ../graduation-experiment-results/chapter2_retrieval/evaluations/dev_v5_round_05 \
  --output ../graduation-experiment-results/chapter2_retrieval/evaluations/dev_v5_round_05_trace_retrieval_metrics.json \
  --report ../graduation-experiment-results/chapter2_retrieval/evaluations/dev_v5_round_05_trace_retrieval_report.md
```

该产物是 post-hoc 开发集补充分析，不是单轮后端检索榜，不替代端到端门禁，也不解锁保留集。正式检索-only比较仍须让各后端直接导出原生排名，再映射到相同证据单元；Precision 因当前 gold 非穷尽相关性池，只能解释为下界。

`first_call_file_retrieval.py` 另将冻结会话的第一次 `search/locate` 返回统一映射到权威文件层，计算 `File Recall@K`、`Complete files@K`、`MRR_file` 与 `nDCG@K`。它适合区分“找错文件”和“已找对文件但未落到精确证据”，但首次查询动作仍由各臂原回答模型生成，所以只能称为 whole-system first-call 分析，不能称为公共查询规划器下的纯后端榜。
