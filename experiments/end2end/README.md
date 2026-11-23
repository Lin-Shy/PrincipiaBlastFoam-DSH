# 第3章专业系统：当前开发入口

更新：2026-11-23。源码、Git、模型API与agent在Linux；Windows用于SSH维护及浏览器人工调试。按任务规模和资源需求选择执行位置：轻量建网、checkMesh、小规模初始化/预处理、摘要统计与绘图可在独立Linux本地执行；大型网格、长时或高资源求解、MPI并行及大型重构/后处理经yhbatch在超算分配节点执行。不得仅按命令名称一刀切；先核对工具、输入规模及CPU/内存/磁盘余量，并设置任务适用的超时和输出限制。公共登录节点仍只做轻量传输、提交和查询，不运行网格或求解。大结果留超算。

真实模型单方腔功能验收与Web基本交互已完成，均包含明确记录的维护恢复，不代表正式批量系统验收。Node/pnpm在workspace/runtime，旧控制实例源码副本已经清理。部署规则见[当前部署](../../deployment/dsh/README.md)，批量准备见[工程计划](PLAN.md)。

本目录包含不同开发批次的实现；旧批次授权、队列、launch intent和剩余额度不属于新批次。launch_integrated_attempt依赖launch_attempt、prepare_system_comparison等公共实现，不能把旧文件名直接理解为可安全删除的重复版本，也不能据入口存在直接运行。

当前没有通过本轮核验的正式批量入口。deployment/acceptance仅支持固定方腔维护任务；deployment/web是人工调试入口，simulation_jobs_max=0，不可用作研究批次。正式批次须独立绑定任务包、运行身份、模型与节点预算、停止规则和独立复核。

实验、题集、研究设计和论文保留在Windows毕业工作区，Linux不依赖本README过去指向缺失同级目录的链接。当前证据导航为Windows的DSH_REMOTE_WORKSPACE.md及graduation-experiment-results/chapter3_end_to_end_evaluation/dsh/CURRENT_DEVELOPMENT.md。
