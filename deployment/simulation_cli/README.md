# simulation_cli：仿真命令专用 MCP

更新：2026-11-23。唯一命令执行入口为 `python -m mcp_servers.simulation_cli.server`，提供 execute、status、logs、cancel。服务描述以服务返回的 instructions 为准：仿真命令优先用本服务，普通 shell 仍可用于其他工作；本服务不做研究规划、物理设计、Git、文档编辑或通用文件管理，也不拦截 shell。

## 接口与实际行为

| 工具 | 行为 |
| --- | --- |
| execute(command, args, case_path, resources?, timeout_seconds=30, location="auto", dry_run=false, request_id?) | 一次调用直接执行或提交；返回持久 task_id。dry_run 仅为可选预览。 |
| status(task_id?) | 有 ID 查询状态、位置、退出结果及产物路径；无 ID 列出能力、版本、上限和限制。 |
| logs(task_id, max_bytes=16384) | 最近有界输出，最多 65536 字节；不下载超算场数据。 |
| cancel(task_id) | 本地记录进程身份后终止进程组，或校验超算 JobID、JobName、属主后取消指定作业；随后查询终态。 |

请求使用独立 argv 字符串，不接受任意 shell 表达式。支持命令集合由 status() 返回，覆盖 blockMesh/checkMesh/snappyHexMesh、常用转换、setFields/mapFields/potentialFoam/topoSet、decomposePar/reconstructPar、常用求解器、postProcess/foamToVTK。**命令在集合中不等于当前两端均已安装或完成真实验收**，应核对各端 available_commands。

本地执行完整算例快照，原算例不被覆盖。不会补写最小控制字典或修改物理参数、数值方法、网格精度、时间范围。下一步使用前一步 status 的 result_path。复制期间输入变化会失败；args 中外部绝对路径及父目录穿越不支持，依赖须先准备在算例内。

```json
{"command":"blockMesh","args":[],"case_path":"cavity","request_id":"cavity-mesh-1"}
{"command":"icoFoam","args":[],"case_path":"<previous result_path>","resources":{"short_test":true},"timeout_seconds":10,"location":"auto","request_id":"cavity-short-test-1"}
```

## 调度、软件与部署边界

操作类别与执行位置分别记录。保守规则检查参数、网格规模、输入体积、工具、当前内存和磁盘余量；估计不明明确记录并转向 HPC。没有学习模型，不声称准确预测耗时。

本地使用独立前缀 `workspace/runtime/openfoam` 中的 conda-forge OpenCFD OpenFOAM **2412 / h946d6a9_1**。上限为 100,000 可识别单元、最多 4 CPU、4 GiB 地址空间、180 秒、32 MiB 输入、128 MiB 总任务输出（单文件 64 MiB），运行时监测时间和输出。默认请求仍为1 CPU、1 GiB、30秒，更高资源须显式请求。CPU按请求设置亲和性与线程上限，CPU时间预算为墙钟上限乘CPU数量；内存须另留512 MiB系统余量，并在worker启动时再次检查。复杂/含动态指令字典可能无法保守估规模；二进制或超过单元上限的网格不自动判为本地可运行。求解器仅在显式 short_test=true 且其他条件满足时允许本地短测，时间上限会终止命令，不改 endTime。

HPC 复用 `experiments/end2end/cluster_job.py` 和 `deployment/remote/linux_scheduler_bridge.py` 的计划、环境哈希及真实调度身份校验，不调用旧批量工作器。经 yhbatch 分配后，在计算节点校验 RUNNING、属主、NodeList 和当前主机，再加载绑定运行环境。公共登录节点只传输、提交、查询及有界证据读取。Foundation OpenFOAM 9 与本地 2412 的网格/求解产物兼容性未证明，验收分别从原始字典建网。

当前 HPC 绑定仅真实确认 blockMesh、checkMesh、setFields、icoFoam；Allrun 可串联这些操作。Allrun 必须是 case/Allrun、无参数、提供人工审阅后的 reviewed_script_sha256，且无 Allclean；哈希是审阅声明与输入身份绑定，不是服务自动理解或安全证明。当前 Allrun 只走 HPC。MPI 语法预留 `mpirun -np N simulationCommand ...`，但当前 MPI 启动器/ABI 未验证、mpi_verified=false，明确返回 environment_missing，不能宣称已覆盖并行求解。

HPC 维护配置及单作业额度位于 `workspace/maintenance/simulation-cli-acceptance-20261123/hpc-config.json`，通过 grant.ledger_path 共享持久提交意图，跨服务状态目录仍共用额度。本轮最多 1 作业、1 task、2 GiB、300 秒，已由作业 **9290965** 用尽。分区整节点独占实际分配 64 CPUs，不能把请求 1 task 当成只占用 1 核计费。批处理单文件输出上限 128 MiB，未部署集群全目录总量硬配额。当前不开放生产或批量派发；没有沿用研究模型预算。

## 持久性、错误与配置

状态为 queued/staging/submitting/submitted/running 及 completed/failed/cancelled/timed_out/unknown。MCP 或 Web 断线不拥有命令生命周期；独立 worker 继续执行。相同 request_id 返回同一任务，不因输入目录新增产物而再次提交；不同参数复用同 ID 被拒绝。不传 ID 时使用参数摘要幂等；确需重新执行须给新 ID。相同算例有活动或未知任务时拒绝并发新任务。

网络未知结果不会自动重提。status 可按唯一 run_id 和属主从 sacct 只读恢复丢失的 JobID；没有唯一匹配则保留 unknown，提交额度仍消耗。该恢复分支尚未做真实断网故障注入。worker 进程丢失时状态保守标记 unknown；本地取消核对 /proc 进程起始身份，不以 PID 单独判断归属。

错误分类为 unsupported（能力/语法未支持）、environment_missing（环境或软件缺失）、resource_insufficient（资源/部署上限不足）、prohibited（路径、脚本审阅、冲突或额度禁止）。仿真本身失败保留 failed、退出结果和日志，不伪装成环境成功。completed 仅表示命令执行通过，不等于物理正确或研究收益。

主要环境变量：

- PRINCIPIA_CASE_ROOT：输入算例根。
- SIMULATION_CLI_STATE：任务、日志与快照根；不进 Git。
- SIMULATION_CLI_OPENFOAM：固定本地前缀；安装源和哈希见 runtime/local-mesh-identity.json（原始安装身份记录）。
- SIMULATION_CLI_HPC_CONFIG：操作者绑定的调度配置；未绑定时只提供可满足条件的本地能力。

正常 bundle 和 Web 均注册独立 simulation_cli。principia_domain 保留字典、配置和证据接口，不再注册 run_case/mesh_case；complete_workflow(require_execution=True) 明确要求使用 simulation_cli。ENABLE_EXECUTION/REQUIRE_EXECUTION 不被全局打开。旧 mesh-only 执行器、配置脚本和包装器已迁出当前路径，规模检查函数仍由新服务依赖。

## 2026-11-23 真实验收

正常 MCP 入口、零模型请求：

- 1000 单元本地建网与 Mesh OK；断开客户端后重连查询、日志和重复请求身份通过。
- 独立 100 单元方腔本地 icoFoam 到 0.02 秒通过；运行中取消另一维护任务通过。
- 当前 Web 配置下 blockMesh、setFields、decomposePar 和 foamToVTK 通过。
- 未支持命令、缺失工具/MPI、资源超限、未审阅脚本及跨状态目录第二作业拒绝均返回明确类别。
- 唯一超算作业 9290965 在 cnode2350 完成，COMPLETED/0:0、7 秒，blockMesh/checkMesh/setFields/icoFoam 到 0.02 秒。分配时 RUNNING 记录、节点及产物小文件哈希已核对，原生结果留集群。
- Web 认证 HTTP 200、插件清单两 MCP active、原有 2 会话可查询；会话、工作区及模型账本哈希不变，仍 3 次模型事件（2 settled、1 unknown）。

初次 1000 单元拉伸网格沿用原时间步导致短测发散，失败日志保留；随后另建原尺度 100 单元求解夹具，服务没有自动改参数。配额查询 lfs quota 自身报错，不能将其返回值当配额证明；df 余量、实际小型上传和作业运行已核对。当前证据仅为维护功能验收。

未验项：运行中的 HPC 取消、真实断网提交恢复、MPI、大网格/长求解、转换及全部求解/重构命令、主机重启自启、完整模型 UI 新工具调用。已有超算算例的直接续接尚未实现；输入转移上限 32 MiB，不宣称通用大型任务全覆盖。

Linux 证据根：`workspace/maintenance/simulation-cli-acceptance-20261123`。Windows 当前报告：`graduation-experiment-results/maintenance/simulation_cli_acceptance_20261123/README.md`。这些原始事件与此前 local_mesh_acceptance 是独立证据，不互相替代。正式第3章两臂评价、第4章和旧批量派发均未启动。


2026-11-23资源上限调整：用户将本地部署上限提高为4 CPU、4 GiB、3分钟。其余输入/输出/网格及脚本/MPI边界保持；超算单作业额度不增加。对应维护证据另存于workspace/maintenance/simulation-cli-resource-limits-20261123，不回填此前单任务验收。

本次资源调整核验：相关Python检查59通过；真实MCP建网通过，求解进程亲和性4核、RLIMIT_AS=4294967296字节、RLIMIT_CPU=720秒（180秒×4核）及线程环境=4；约33秒后主动取消成功，超过4CPU/4096MiB/180秒的本地请求均被拒绝。此核验没有分配并实际占满4 GiB，也未等待完整180秒墙钟超时；墙钟监控路径沿用已验收实现。
