---
name: blastfoam-execution
description: 对已批准的 blastFoam/OpenFOAM 算例执行可复现预检和求解，保存日志并分类运行状态。
---

# blastFoam 求解执行

只有算例配置验证通过后，才能使用本 Skill。

## 操作步骤

1. 记录算例路径、solver、OpenFOAM/blastFoam 环境、命令行和输入清单。
2. 执行非破坏性预检：检查预期文件、可用时解析字典、发现可执行文件、检查磁盘空间，以及检测残留进程或旧输出。
3. 只执行已批准的算例，完整保存 stdout、stderr 和计时信息；运行期间不得修改物理设置或字典。
4. 综合退出状态与日志证据分类结果，检查致命错误、浮点异常、发散、非有限值、缺失库、提前终止和正常结束标记。
5. 宣称成功前，确认预期时间目录和场文件确实存在。

## 输出

生成 `execution_report.md` 和 `execution_status.json`。JSON 必须包含状态、命令、退出码、开始/结束时间、日志路径、最后完成时间、检测到的失败标志和输出证据。环境不可用时使用 `blocked`；已经尝试执行但结果无效时使用 `failed`。


## Windows 开发、Linux 远程执行

当配置了 principia_simulation MCP 时，Windows 本地预检的 Linux 环境阻断不能用于判定远端环境不可用。先查询远端服务状态；用 principia_simulation_files.upload_simulation_case 上传已批准的本地算例，再将返回 case_id 传给 run_simulation。提交返回 job_id，随后轮询状态和有界日志，不把 MCP HTTP 请求保持到求解结束。

终态后读取 get_simulation_result，再用 download_simulation_result 下载并核对 SHA256。本地解压、核对实际时间目录、字段和有限值后，生成本章 execution_report.md 与 execution_status.json。completed 仅表示进程退出码为0，不能据此宣布完整任务或物理验证成功。cleanup_simulation 只能在本地归档及证据检查完成后使用下载散列调用。Linux 服务不生成第3章七项产物，也不包含智能体角色。
