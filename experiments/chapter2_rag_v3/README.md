# Terra候选优化入口（2026-10-28）

候选开发使用`terra_candidate.py --execute`；原生Responses候选使用同入口的`--native`。这是独立候选试验，未修改冻结Prompt、五档规则或原Sol结果。流重建、身份与usage校验由`terra_stream.py`/`terra_native.py`执行；候选协议与技术恢复修订在正式实验release/protocol中。请求medium/high不等于独立证实服务端内部推理等级。

当前接口控制受上游过载和无回执断连阻塞，没有新候选通过验收，不能把候选评分用于正式替换。诊断入口为正式实验evaluation/judges/terra_candidate/index.html。原正式补评分支的验收门控继续保留；本候选入口不会自动解锁旧配置。

# 当前Test160裁判接口（2026-10-28）

GPT新增缺评由 `test160_terra.py` 调用 `gpt-6.1-terra`，配置在 `config/llm/test160_gpt_runtime.json`；DeepSeek继续原缺评队列。已有Sol评分与实际响应身份保留，不能追认为Terra评分。模型变更单列正式 `release/protocol/test160_gpt_terra_amendment.json`，不覆盖冻结Manifest。审计支持逐请求真实模型，最终统计须披露并分层核验此变更。

Terra仅填补有效回答的缺评，不重新生成回答。已保存评分优先复用，传输未决不重发，共享两请求槽与三次恢复上限。创建 `test160_runs/PAUSE_gpt_terra` 可在当前请求结束后停止新增调用。运行结束后使用 `test160_closure_audit.py` 核查；未闭合图表继续使用统一上下界。

# 第2章正式实验执行器

唯一结果与运行说明见[正式实验README](../../../graduation-experiment-results/chapter2_retrieval/README.md)。位置由runtime_layout.py和正式release/manifests/layout.json统一解析；历史原件不改，旧路径经显式映射解析。评分规则、Prompt与检索参数保持冻结，原人工审计未通过的事实保留。

离线验证：在DSH项目根运行 `.local/knowledge-qa-venv/Scripts/python.exe -m unittest discover -s experiments/chapter2_rag_v3 -p test*.py`；全数据验收使用正式根release/validation/migration_verify.py。Test160仅可先运行 `test160_runner.py check`，execute/score必须有负责人批准且绑定当前Manifest。Single-Pass补充矩阵单独批准。历史准备阶段未运行Test160；当前已获授权运行，最新状态以正式README为准。

原实现与新旧源码哈希在正式release/protocol/source_originals及release/manifests/code_rebinding.json。legacy目录仅追溯历史，不是当前实验入口。私有.env仍由config/llm安全管理，冷备份不包含私有凭据。
