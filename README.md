# PrincipiaBlastFoam-DSH：第3章专业执行系统

2026-11-23。源码开发、Git、依赖和agent运行均在Linux的agent账号完成；Windows只通过SSH下达命令和查看。开发工作区与已验收运行实例分开绑定版本，不自动部署或启动任务。

## 当前入口

- `src/principia_core/`：OpenFOAM配置、字典编辑、领域服务与证据处理。
- `mcp_servers/principia_domain/`：第3章领域MCP；不加载知识问答服务，本机仿真入口关闭。
- `mcp_servers/simulation/`：远端接口代码；是否已接入当前Linux操作者须按实测记录判断。
- `experiments/end2end/`：第3章开发与评测实现，旧批次预算不自动沿用。
- `packages/principia-dsh-bundle/`：可选领域bundle，旧五专家编排不是研究约束。
- `deployment/dsh/linux-controller-plan.md`：部署规则、状态与后续单小算例验收条件。

第2章实现、检索后端、知识资源和测试已完整迁回Windows的 `D:/1/graduation-projects/chapter2-knowledge-qa/`；Linux不保存第2章活动源码，不作为本项目子目录或默认依赖。原Git历史及迁移前未提交状态完整保存，源码移动不改写冻结研究证据。

## 无模型维护

在Linux加载开发工作区的 `environment.sh` 后，可运行 `dsh-dev --profile headless --dump-config` 查看配置。该命令不请求模型。普通任务仍须明确模型、任务与预算；当前只迁移维护，不启动真实模型、小算例或正式实验。

建网、checkMesh、初始化、分解、求解、重构和计算型后处理必须经yhbatch在超算实际分配节点执行。登录节点只做轻量传输、提交和查询。大结果留超算，Linux仅留源码、依赖、配置和有界控制记录/结果引用。agent直接使用所需私钥，不要求root代操作；完整账号权限不等于OS沙箱。

## Git连接与恢复副本清理完成

2026-11-23：GitHub读取、fetch和推送dry-run均验证通过，仓库专用Deploy key已启用写权限；没有实际推送代码或创建分支。收到用户明确确认后，已删除四个迁移恢复包和inactive raw目录，Windows完整恢复包仍保留。活动配置、集群凭据及原Git历史保持完整，pip check与DSH正常配置入口通过。本轮没有模型请求或仿真。


## Current simulation command service (2026-11-23)

[simulation_cli tools, deployment and verified boundaries](deployment/simulation_cli/README.md). Command execution uses execute/status/logs/cancel; domain configuration/evidence tools remain separate. Single maintenance acceptance is not a research experiment.
