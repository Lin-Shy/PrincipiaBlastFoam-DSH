---
name: blastfoam-retrieval
description: 通过 Principia MCP 服务执行可追溯的两阶段检索，获取 blastFoam 教程、字典、变量和用户手册证据。
---

# blastFoam 知识检索

工作流决策依赖 blastFoam 教程、字典条目、变量或用户手册结论时，使用本 Skill。

## 操作步骤

1. 依赖知识图谱前，先调用 `mcp__principia_retrieval__get_status`。
2. 优先使用范围明确的确定性工具：`get_case_by_intent`、`get_files_for_case` 和 `find_variable`。
3. 搜索内容时，先通过 `search_case_content` 或 `search_user_guide` 获取候选项，再根据选定的 `result_id` 请求详情；避免加载无关的大文件。
4. 已知文件使用 `get_file_content`；明确修改需求使用 `get_modification_targets`。
5. 在 `workflow_evidence.md` 中保存工具名、查询、选定结果 ID、算例/文件路径，以及该结果支持的决策。

如果 MCP 服务不可用或证据不完整，应报告限制，不得编造教程路径、字典值或文档结论。
