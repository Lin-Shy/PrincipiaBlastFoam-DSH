# 第3章DSH源码与运行维护

2026-11-23当前状态：迁移维护及真实模型单方腔功能验收已完成（含维护恢复）。DSH源码、Git、依赖和agent运行在Linux；Windows通过SSH维护、浏览器人工调试。Web基本交互验收已通过（含一次用户批准的恢复）；simulation_cli 命令服务已重建并完成有界维护验收，暂不启动批量实验或复用旧预算。

## 目录边界

本目录只维护第3章。问答评测、retrieval_method、知识资源、问答MCP和相关测试已拆分并完整迁回Windows的D:/1/graduation-projects/chapter2-knowledge-qa/；不设旧目录兼容链接，不默认加载其服务。OpenFOAM领域服务、字典编辑、算例/结果接口及领域MCP归本项目。原Git历史、原未提交状态及冻结证据不得改写。

## 执行与存储

- agent、模型API、领域工具及控制逻辑在Linux的agent账号运行，源码与已验收运行实例分开部署并记录身份。
- 按任务规模和资源需求选择执行位置：轻量建网、checkMesh、小规模初始化/预处理、摘要统计与绘图可在独立Linux本地执行；大型网格、长时或高资源求解、MPI并行及大型重构/后处理经yhbatch在超算分配节点执行。不得仅按命令名称一刀切；先核对工具、输入规模及CPU/内存/磁盘余量，并设置任务适用的超时和输出限制。公共登录节点仍只做轻量传输、提交和查询，不运行网格或求解。核对真实作业归属、NodeList和当前主机，环境变量不能代替资源分配。
- Linux控制机可运行资源可控的轻量任务；超算公共登录节点不运行网格或求解。大结果留超算，仅回传有界日志、状态、JobID、路径、大小/哈希与摘要。
- agent按用户授权直接使用完整集群凭据，不要求root专用操作者；严格主机校验，私钥、API凭据不得输出或提交Git。目录和应用检查不是OS沙箱。
- 旧批量工作器及历史预算不得自动恢复。后续正式批次须独立记录运行身份、资源/请求上限、输入边界和停止条件；单方腔专用桥不等于通用批量入口。

## 开发与核验

固定上游版本和锁文件，复用已有SDK接口及官方provider，profile patch替换config时重列所需字段，新增插件使用已验证的insert语法。不将提示词当执行约束。修改调用路径时同步调用方和对应测试。

验证应覆盖当前bundle、Python相关回归、正常profile配置及无模型MCP/本地夹具。仅报告实际执行的检查；历史测试或冻结模块已退役时保留身份，不为通过旧测试恢复工作器。研究效果须以真实封存证据解释，部署与平台修复不算专业能力收益。第4章Pi独立维护。

2026-11-23分工补充：第2章只在Windows开发维护，Linux第2章工作区及editable依赖已移除，第3章独立检查58通过、9跳过。迁移拆分、调度与单算例验收、Web和文档已分四组提交，并实际推送codex/chapter3-linux-web；远端核验通过，main仍为ad364ba357f9857268a2283f4f26bbcfa507345e。后续修改先检查工作区，禁止覆盖其他未提交改动。用户已明确确认清理四个历史恢复包及inactive raw目录，执行后核验活动配置与凭据不变；Windows恢复包保留，不改写原Git历史。

2026-11-23后续验收最终状态：本规划会话完成真实deepseek-v4.1-flash与一个100单元方腔功能链（含维护恢复）。唯一作业9283604，yhbatch分配cnode4754，COMPLETED/0:0，28秒到0.02秒；八项交付核验通过。总40请求含1未知用量，记录传输失败、输出截断、报告纠正及最终预算拒绝。既有控制实例未覆盖，无整章或第4章启动。详情 deployment/acceptance/README.md 与 workspace/runs/single-case-acceptance-delivery-20261123/verification.json。此前待执行是迁移阶段历史；禁止自动复用本次launch intent或额度。

## 多版本清理（2026-11-23用户澄清）
同一内容默认只留最新有效版本；无依赖、已被替代且无独立价值的旧版本直接清理。不同实验、协议和唯一原始证据不是互相替代版本。确需额外保留旧版本时，必须向用户说明路径、用途、删除影响并询问是否保留；不得仅改名历史或归档规避清理。先核对版本关系和当前依赖，用户具体决定沿用，不输出凭据。

2026-11-23 current simulation command entry: simulation_cli.execute/status/logs/cancel. Bounded local commands and short_test solvers use conservative scale/resource checks; scripts and heavy work use the scoped scheduler binding. The mesh_case/run_case MCP command tools and mesh-only backend have been retired. General shell remains available; no research planning or shell interception is added. See deployment/simulation_cli/README.md for actual capabilities, one-job grant consumption, evidence and unverified paths. No batch research or new model request was started.

2026-11-23本地资源上限按用户要求提高为4 CPU、4 GiB地址空间、180秒；默认请求仍为1 CPU、1 GiB、30秒。按请求设置CPU亲和性、线程上限与CPU时间预算，保留512 MiB系统内存余量并在启动时重查。其余网格/输入/输出、Allrun与MPI边界不变，超算额度不增加。真实4CPU/4GiB进程和跨过旧30秒的运行/取消已核验；新维护证据为workspace/maintenance/simulation-cli-resource-limits-20261123。
