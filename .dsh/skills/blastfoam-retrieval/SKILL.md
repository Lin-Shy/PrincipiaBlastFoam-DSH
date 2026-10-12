---
name: blastfoam-retrieval
description: 兼容已有 Principia MCP 检索调用与 result_id 详情读取；新的教程和手册检索使用 blastfoam-knowledge。
---

# blastFoam 知识检索

新的教程选择、配置定位和用户手册检索使用 [blastfoam-knowledge](../blastfoam-knowledge/SKILL.md)，它保存固定版本语料、预构建图谱和本地查询脚本。已有 MCP 调用或 result_id 需要继续读取时，使用下面的兼容流程；两套索引的结果 ID 不可混用。

未知位置的新任务通过 blastfoam-knowledge 的 `locate.py` 从需求定位来源及关联阅读位置；此处 MCP 是旧接口兼容流程。原文已足够时不追加图谱调用；以答案质量和累计检索/模型成本判断收益，不以全语料压缩比宣称 Token 节省。兼容入口不代表已启用新版手册语义补充。

## 操作步骤

1. 依赖知识图谱前，先调用 `mcp__principia_retrieval__get_status`。
2. 优先使用范围明确的确定性工具：`get_case_by_intent`、`get_files_for_case` 和 `find_variable`。
3. 搜索内容时，先通过 `search_case_content` 或 `search_user_guide` 获取候选项，再根据选定的 `result_id` 请求详情；避免加载无关的大文件。
4. 已知文件使用 `get_file_content`；明确修改需求使用 `get_modification_targets`。
5. 在 `workflow_evidence.md` 中保存工具名、查询、选定结果 ID、算例/文件路径，以及该结果支持的决策。

如果 MCP 服务不可用或证据不完整，应报告限制，不得编造教程路径、字典值或文档结论。
