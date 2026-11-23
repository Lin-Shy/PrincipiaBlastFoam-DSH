---
name: blastfoam-quality-review
description: 独立审查 PrincipiaBlastFoam 运行的物理、配置、执行、后处理、来源与产物完整性。
---

# blastFoam 质量审查

2026-11-23执行边界：agent和源码开发在Linux，Windows仅SSH控制；所有仿真及计算型后处理必须通过yhbatch在超算实际分配节点执行，不能在控制机/登录节点运行。大结果留超算，本机仅配置与有界控制记录。当前仅迁移维护，不启动实验。

只有工作流不再修改算例和阶段报告后，才能使用本 Skill。

## 只读审查

检查用户需求、`physics_report.md`、算例字典与修改清单、solver 日志、`execution_report.md`、`execution_status.json`、`post_processing_report.md` 和生成的场文件。所有结论都要与原始文件交叉验证，不能照抄前序角色的判断。

审查内容包括：

- 物理模型适用性与假设可追溯性；
- 教程选择和修改来源；
- 字典、量纲、边界和场一致性；
- solver 终止状态、数值健康度和输出完整性；
- 后处理有效性、单位、采样和可复现性；
- 必需产物以及不同报告之间的矛盾。

审查员不得执行命令，也不得写入或修改文件。它只返回用于 `review_report.md`、`workflow_evidence.md` 和 `artifact_contract.json` 的结构化内容；确定性写入器或父智能体在逐字保留审查响应后负责落盘。

采用失败关闭：缺少决定性证据时不得给出通过结论。针对每项产物记录路径、是否存在、生产阶段、证据、验证结果和原因。
