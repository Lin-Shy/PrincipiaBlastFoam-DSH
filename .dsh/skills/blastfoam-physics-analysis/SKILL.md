---
name: blastfoam-physics-analysis
description: 在创建或修改任何算例文件前分析爆炸物理问题，并选择有证据支撑的 blastFoam 教程。
---

# blastFoam 物理分析

新建仿真或物理模型发生实质变化时，首先使用本 Skill。

## 操作步骤

1. 把需求规范为几何、维数、材料、炸药/源项、初始状态、边界、目标观测量以及时间/长度尺度。
2. 使用 `mcp__principia_retrieval__get_status` 获取 MCP 服务状态。
3. 使用 `mcp__principia_retrieval__get_case_by_intent` 查找候选教程；选择前检查相关文件和用户手册证据。
4. 明确哪些物理与数值特征可以原样迁移，哪些必须修改。
5. 定义稳定性风险、预期定性行为、定量检查，以及能够推翻当前配置方案的证据。

## 输出

写入或返回 `physics_report.md` 交接内容，其中包含所选教程路径、检索证据、假设、方程/模型、边界与初始条件、数值方案、未决问题和验收标准。本阶段不得编辑算例或执行 solver。
