---
name: blastfoam-case-setup
description: 根据已批准的物理分析交接结果和检索到的教程证据，在工作区内构建或修改 blastFoam 算例。
---

# blastFoam 算例配置

只有物理分析已经确定合适教程和明确修改项后，才能使用本 Skill。

## 操作步骤

1. 使用 `mcp__principia_retrieval__get_files_for_case` 确认源教程。
2. 使用 `mcp__principia_retrieval__get_modification_targets` 和 `mcp__principia_retrieval__find_variable` 定位准确的字典与条目；编辑前必须检索原始内容。
3. 把教程复制到工作区内的新算例，禁止原地编辑教程或 OpenFOAM/blastFoam 安装目录。
4. 只实施能够保持整体一致性的最小修改，并为每项修改记录旧值、新值、单位/量纲、原因和来源。
5. 检查必需字典、量纲、路径、边界/场一致性、网格设置、时间控制、写出控制和可执行脚本。

## 阶段交接

返回算例路径、源教程、变更文件清单、已执行检查、警告和推荐的准确执行命令。配置阶段不得运行生产 solver。
