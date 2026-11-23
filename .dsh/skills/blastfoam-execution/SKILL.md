---
name: blastfoam-execution
description: 对已批准的 blastFoam/OpenFOAM 算例执行可复现预检和求解，保存日志并分类运行状态。
---

# blastFoam 求解执行

2026-11-23执行边界更新：agent和源码开发在Linux，Windows用于SSH维护及浏览器交互。按任务规模和资源需求选择执行位置：轻量建网、checkMesh、小规模初始化/预处理、摘要统计与绘图可在独立Linux本地执行；大型网格、长时或高资源求解、MPI并行及大型重构/后处理经yhbatch在超算分配节点执行。不得仅按命令名称一刀切；先核对工具、输入规模及CPU/内存/磁盘余量，并设置任务适用的超时和输出限制。公共登录节点仍只做轻量传输、提交和查询，不运行网格或求解。大结果留超算；本规则不自动启动批量实验。

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

执行仿真命令优先使用 simulation_cli.execute；status 无参数查看当前能力与边界，再用任务ID查询状态、日志或取消。轻量操作和显式有界短测可在独立Linux执行；Allrun 当前须经审阅绑定哈希并走超算。未知规模或环境不满足时按返回原因处理，不自动改物理和数值条件。一般shell仍可直接使用，本服务不拦截shell。

超算终态后核对JobID、节点、退出码、输出路径及有界摘要；大结果留超算。轻量本地操作记录主机、工具版本、输入/输出身份、资源与终态，不能伪造调度回执。退出码0不等于完整任务或物理验证成功。

2026-11-23 current simulation command entry: simulation_cli.execute/status/logs/cancel. Bounded local commands and short_test solvers use conservative scale/resource checks; scripts and heavy work use the scoped scheduler binding. The mesh_case/run_case MCP command tools and mesh-only backend have been retired. General shell remains available; no research planning or shell interception is added. See deployment/simulation_cli/README.md for actual capabilities, one-job grant consumption, evidence and unverified paths. No batch research or new model request was started.
