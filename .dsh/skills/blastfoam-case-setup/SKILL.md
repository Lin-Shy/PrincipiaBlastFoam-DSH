---
name: blastfoam-case-setup
description: 根据已批准的物理分析交接结果和检索到的教程证据，在工作区内构建或修改 blastFoam 算例。
---

# blastFoam 算例配置

2026-11-23执行边界：agent和源码开发在Linux，Windows仅SSH控制；所有仿真及计算型后处理必须通过yhbatch在超算实际分配节点执行，不能在控制机/登录节点运行。大结果留超算，本机仅配置与有界控制记录。当前仅迁移维护，不启动实验。

用于教程和修改目标已确定的算例配置；用户直接给出二者时，可据此开始。

## 操作步骤

1. 通过基础文件读取/搜索工具确认公开源教程及版本，记录从已核对教程根目录复制的实际路径。
2. 按知识技能使用 `locate_case_edits` 定位修改及来源；仅对影响修改的证据缺口补查原始内容。
3. 把教程复制到工作区内的新算例。已定位具体教程时，可用 `initialize_case`，将 `tutorial_path` 设为该案例目录、`case_path` 设为新副本；含 Allrun/Allclean 的目录会被直接复制，不重新选择案例。工具返回 `initialized=true` 后再编辑；已有非空目标默认保留。禁止原地编辑教程或 OpenFOAM/blastFoam 安装目录。
4. 路径和取值已确定时，使用 `mcp__principia_domain__edit_case_dictionaries` 批量编辑副本。传入 `case_path` 和 `edits`，每项包含 `path`（如 `constant/phaseProperties`）、`entry`（如 `air/transport/As`）、`value`（OpenFOAM值文本，不含末尾分号；null删除）。工具创建缺失父字典，保留正则回退，并在所有修改文件解析通过后写回。需要预览时使用 `dry_run=true`。它不推断物理配置，不处理含指令/变量替换的字典；此类文件按具体错误另行处理。记录修改原因及来源。
5. 根据修改范围核对受影响的字典、量纲和依赖。解析通过只证明字典可读；记录尚未执行的运行或物理验证。对不影响当前修改的疑问，不扩展为完整求解器源码审查。

## 阶段交接

返回算例路径、源教程、变更文件清单、已执行检查、警告和推荐的准确执行命令。配置阶段不得运行生产 solver。
