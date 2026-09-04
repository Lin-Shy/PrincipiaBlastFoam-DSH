---
name: blastfoam-workflow
description: 编排完整 blastFoam 工作流，依次完成物理分析、算例配置、求解、后处理和独立质量审查。
---

# blastFoam 总工作流

收到完整的自然语言 blastFoam/OpenFOAM 仿真需求时使用本 Skill。

## 阶段闸门

必须按顺序执行以下阶段。传递给每个 subagent 的提示应自包含，至少包括用户需求、活动工作区、上一阶段交接内容、必需输出和验收标准。

1. 调用 `blastfoam_physics_analyst`。要求在 `physics_report.md` 中给出假设、维数、材料模型、边界、数值风险、教程证据和可测验收标准。
2. 只有物理交接结果被接受后，才能调用 `blastfoam_case_setup`。要求生成工作区内算例、变更文件清单、语法/量纲检查，并且不得运行生产 solver。
3. 只有配置验证通过后，才能调用 `blastfoam_execution_specialist`。要求记录准确命令、环境、solver 日志分类，并生成 `execution_report.md` 和 `execution_status.json`。
4. 只有获得执行证据后，才能调用 `blastfoam_postprocessor`。要求生成可复现观测量和 `post_processing_report.md`。
5. 所有前序证据稳定后调用 `blastfoam_quality_reviewer`。审查员只读且必须失败关闭。逐字保留它的响应，再由确定性写入器或父智能体仅生成 `review_report.md`、`workflow_evidence.md` 和 `artifact_contract.json`。

存在依赖关系的阶段不得并行；同一阶段中相互独立的检索可以并行。

## 完成条件

成功响应必须给出算例目录，并逐项说明所有必需产物。明确区分 `passed`、`failed`、`blocked` 和 `not-applicable`；不得仅根据进程退出码推断 solver 成功。
