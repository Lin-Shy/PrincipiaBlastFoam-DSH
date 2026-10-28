# 第2章Test160实验与评分

双裁判固定使用GPT-6 Sol（gpt-6-sol）与DeepSeek V4.1 Flash（deepseek-v4.1-flash）。活动配置由config/llm/models.yaml与judging.yaml管理。缺评恢复使用test160_resume_scores.py，原始请求、有效评分与未决状态全部复用；统计审计使用test160_closure_audit.py，结果入口由test160_progress_page.py生成。评分未闭合时保持固定分母和统一上下界，不发布最终排名。

唯一结果与运行说明见[正式实验README](../../../graduation-experiment-results/chapter2_retrieval/README.md)。位置由runtime_layout.py和正式release/manifests/layout.json统一解析；历史原件不改，旧路径经显式映射解析。评分规则、Prompt与检索参数保持冻结，原人工审计未通过的事实保留。

离线验证：在DSH项目根运行 `.local/knowledge-qa-venv/Scripts/python.exe -m unittest discover -s experiments/chapter2_rag_v3 -p test*.py`；全数据验收使用正式根release/validation/migration_verify.py。Test160仅可先运行 `test160_runner.py check`，execute/score必须有负责人批准且绑定当前Manifest。Single-Pass补充矩阵单独批准。历史准备阶段未运行Test160；当前已获授权运行，最新状态以正式README为准。

原实现与新旧源码哈希在正式release/protocol/source_originals及release/manifests/code_rebinding.json。legacy目录仅追溯历史，不是当前实验入口。私有.env仍由config/llm安全管理，冷备份不包含私有凭据。
