# 独立Linux agent与C集群求解：当前部署规则

更新：2026-11-23。源码、Git、依赖及agent运行在Linux的agent账号，Windows通过SSH维护、浏览器人工调试。迁移、离线部署和真实模型单方腔功能验收已完成（含维护恢复）；Web基本交互验收已通过。当前不启动批量实验。研究问题、冻结协议及历史成绩不变。

## 当前职责与存储

| 位置 | 当前职责 | 保留内容 |
| --- | --- | --- |
| Windows | SSH开发维护与浏览器人工调试 | 配置、清单、校验报告、恢复材料；按需取回交付物，不承担agent运行 |
| 独立Linux | Git源码开发、依赖维护、agent会话、模型API请求、领域工具、配置编辑、任务编排、调度提交和查询 | 完整源码与Git、运行时及必要依赖、算例配置、有界控制日志和结果引用 |
| 超算公共登录节点 | 轻量目录维护、传输、提交、查询 | 不启动agent、模型服务、网格或求解进程 |
| 超算分配计算节点 | 大型网格、高资源求解及大型后处理；已提交作业按固定计划执行 | 在新建的唯一任务目录内生成数据 |
| 超算存储 | 保存原生仿真结果、几何大文件及历史大归档 | 原生场、时间目录、processor数据和完整归档留存，按路径与哈希引用 |

当前控制机就是既有 `yan_yun_agent` 指向的个人服务器，使用非root的 `agent` 账号，不另设一台未知开发机。集群凭据按用户授权由agent直接持有和使用，0700/0600权限保护，严格校验known_hosts。该凭据仍有完整系统账号权限，不是沙箱。

源代码与运行实例分别管理：Linux开发工作区中的Git源码不会自动更新已安装运行实例。后续每次部署须显式绑定源码版本/哈希、依赖和配置；新批次记录Linux运行时身份，不能把旧Windows批次视作新环境验收。

## 已完成与未完成

已完成真实deepseek-v4.1-flash单方腔功能验收：唯一作业9283604，经yhbatch分配cnode4754，COMPLETED/0:0，100单元求解到0.02秒，28秒；八项交付通过核验。40次请求含1次未知用量，传输恢复、输出截断、报告纠正及预算拒绝保留，不解释为无干预自主成功。详见[验收说明](../acceptance/README.md)和工作区runs/single-case-acceptance-delivery-20261123/verification.json。旧额度和launch intent不复用。

Web基本交互已验收：真实聊天、get_status输入输出展开、执行轨迹、刷新历史、服务重启历史恢复与SSH隧道自动重连。首请求传输失败并保留未知用量，用户明确批准一次人工恢复后新消息成功。共3次请求、2成功、1未知，已报告21002 token，总上限100不变；没有节点作业。Web新增工具组合不能由headless单算例验收替代。独立100次请求上限跨重启保留账本，不构成正式批次预算。

正式批次前仍需核验：两臂Linux运行身份与可比公开输入边界；各任务与调度入口的适配；提交结果不明时先查询、不重提；模型未知用量停止派发；原生结果远端保留及有界回传；交件封存与独立复核。单方腔固定桥不等于通用exchange操作者。按任务规模和资源需求选择执行位置：轻量建网、checkMesh、小规模初始化/预处理、摘要统计与绘图可在独立Linux本地执行；大型网格、长时或高资源求解、MPI并行及大型重构/后处理经yhbatch在超算分配节点执行。不得仅按命令名称一刀切；先核对工具、输入规模及CPU/内存/磁盘余量，并设置任务适用的超时和输出限制。公共登录节点仍只做轻量传输、提交和查询，不运行网格或求解。

本文引用的论文/PPT部署说明仍待按实际证据同步；本轮不改研究结论，第4章Pi独立维护。

## 运行分工

```text
Windows 浏览器／SSH：查看与控制，可断开
                |
独立 Linux 控制主机
  ├─ 第3章 DSH：会话、模型 API、领域工具、算例编辑
  ├─ 独立运行目录：配置、有界日志、账本、检查点、结果引用
  └─ SSH 调度工具：agent 账号按用户授权持有集群凭据
                |
C 集群公共登录节点：轻量传输、提交、查询
                | yhbatch
调度分配的计算节点：大型网格、重求解、大型后处理
```

控制主机不需要本地运行大模型，继续调用既有模型 API。控制主机可执行资源可控的轻量建网、预处理和分析；不默认承载高资源求解。Windows 断开后，模型连接、提交服务及日志均须不依赖 Windows 转发或本地进程。第4章如迁移，单独部署 Pi、预算账本、配置和运行目录，不继承第3章系统。

2026-11-23运行组件整理：Node/pnpm已迁到workspace/runtime，正常Web配置、认证页面、只读领域MCP与持久账本检查通过；旧controller_20261122/source、application和退役启动器已删除。模型请求与节点作业均未增加。记录见workspace/runtime/verification.json与cleanup.json。

## 当前工具限制与部署待办

上述为执行位置政策，不代表本地OpenFOAM已经安装。2026-11-23加载当前environment.sh后，blockMesh、checkMesh、setFields、icoFoam、blastFoam均未出现在PATH。领域MCP的run_case及require_execution=True仍无条件拒绝整流程；Web设置ENABLE_EXECUTION=false。该开关不能区分轻量建网和Allrun内重求解，不应直接全部打开。轻量步骤应使用可确认资源范围的独立命令或后续专用接口；本轮只更新说明和排查，不修改求解执行器、安装软件或运行仿真。集群提交器继续校验实际分配节点，该保护不应删除。


2026-11-23 current simulation command entry: simulation_cli.execute/status/logs/cancel. Bounded local commands and short_test solvers use conservative scale/resource checks; scripts and heavy work use the scoped scheduler binding. The mesh_case/run_case MCP command tools and mesh-only backend have been retired. General shell remains available; no research planning or shell interception is added. See deployment/simulation_cli/README.md for actual capabilities, one-job grant consumption, evidence and unverified paths. No batch research or new model request was started.
