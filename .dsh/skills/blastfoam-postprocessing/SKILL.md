---
name: blastfoam-postprocessing
description: 在不改变已批准算例配置的前提下，验证 blastFoam 结果场并计算可复现的观测量。
---

# blastFoam 后处理

获得执行证据后使用本 Skill；未完成或失败的运行也可以用它进行诊断。

## 操作步骤

1. 读取 `execution_status.json`、solver 日志和可用时间目录，不能假设最新目录一定有效。
2. 针对每个目标观测量检查必需场、量纲、采样位置、有限值和时间覆盖范围。
3. 运行可复现的 OpenFOAM 工具或分析命令，并记录命令、输入、选择条件、单位和输出路径。
4. 区分物理零值与缺失、无效、截断或尚未计算的数据。
5. 把结果与物理验收标准对照；发现偏差时如实标记，不得反向改写算例配置。

## 输出

生成 `post_processing_report.md`，包含来源、有效性检查、派生指标、按需生成的图表、局限性，以及明确的 `passed`、`failed`、`blocked` 或 `partial` 结论。
