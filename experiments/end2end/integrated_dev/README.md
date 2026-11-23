# 章内集成开发工具

2026-11-23迁移更新：DSH源码开发、Git操作、依赖维护与agent运行全部在Linux的agent账号下完成；Windows只通过SSH下达命令与查看，不再维护DSH源码。开发工作区与已验收运行实例分开绑定版本；本轮只迁移维护和无模型核验，不启动真实模型、仿真或总目标实验。大结果留超算，仿真仍只走调度分配节点。

2026-11-23当前运行规则：agent、模型API及领域/控制处理转到独立Linux，源码开发和Git维护也在Linux，Windows仅下达命令和查看；仿真全部经超算调度分配节点执行，大结果留超算。本轮只维护项目，真实模型和单个小算例端到端验收待执行，见[当前方案](../../../deployment/dsh/linux-controller-plan.md)。Linux已部署四项领域工具/三个技能的离线验证，不代表本目录所有Windows入口、候选策略或操作者已移植。下文PowerShell示例及旧批次结果保留开发与历史身份，不直接作为Linux生产命令或新预算依据。

[工程任务入口](../README.md) · [当前实验状态](../../../../graduation-experiment-results/chapter3_end_to_end_evaluation/dsh/development_batch18_20261118/STATUS.md)。本页仅说明 `start.py` 的离线工具验收；它不代表真实模型实验的运行状态。

从毕业工作区根运行（PowerShell）：

~~~powershell
$py = 'PrincipiaBlastFoam-DSH/.venv/Scripts/python.exe'
$entry = 'PrincipiaBlastFoam-DSH/experiments/end2end/integrated_dev/start.py'
& $py -B -X utf8 $entry professional D:/my-engineering-work catalog
~~~

将 professional 换成 general 即使用同一上游通用底座。catalog 返回运行中 DSH 实际可见的工具名和 skill 服务查询结果。invoke 按名字通过同一注册表调用工具：在用户工作目录放入 pump.txt（秒、绝对压力 Pa，每行一组），另存参数文件 args.json，例如：

~~~json
{"input":"pump.txt","output":"metrics.json","ambient":100000,"start":0,"end":2}
~~~

~~~powershell
& $py -B -X utf8 $entry professional D:/my-engineering-work invoke pressure_window --args-file D:/my-engineering-work/args.json
~~~

输出留在指定工作目录。工具复用已有 observe.py 与解析模块；按显式基准与窗口计算，不依赖 S10 测点或参考值。输入单位需由调用者确认。skill 服务提供工程交付说明及已有质量审查资料；后者用于实际仿真审查，不是本次水泵测试的评分器。通用版仍使用 base/headless 的原生工具。注册表还可能列出需要另行配置的服务工具；列名不表示已连通。本版没有连接问答 MCP、集群、付费模型或旧五专家服务，也不载入场景专用导出器。

accept 是固定测试驱动。在两个新目录放入相同的 pump.txt，内容为三行：`0 100000`、`1 100200`、`2 100000`。分别运行 `general <目录> accept` 与 `professional <目录> accept`。本机需具备原生 write 的硬链接权限。两版均由 harness 执行 read/write；专业版另通过 skill 加载全文，再调用 pressure_window。测试记录在 acceptance.json。三角形时序的独立预期值为峰值 200 Pa、峰时 1 s、正超压面积 200 Pa·s。目录需是可信用户工作区；本入口没有实现 OS 沙箱。

运行依赖为现有章内 Node/DSH 快照、项目 Python 环境、以及只读的已冻结 general 配置模板；每次调用在工作目录建立临时 profile，退出时清理。该入口是运行中的 harness 工具前端，不提供无凭据的模型聊天功能。

2026-11-22 的普通流体专业系统修订在同一入口加载 measurement-review 技能及 convert_volume_rates、interval_coverage、latest_attempt_events 三个原生工具。measurement_replay.py 从公开包重放旧交件偏差，measurement_live.py 经原生会话派发诊断题集，measurement_summary.py 核对封存件并分层汇总。[回归记录与逐题成绩](../../../../graduation-experiment-results/chapter3_end_to_end_evaluation/dsh/measurement_diagnostic_20261122/RESULT.md)

PIPE-01 从空工程双臂验证的[本轮判定、节点原件与重建证据](../../../../graduation-experiment-results/chapter3_end_to_end_evaluation/dsh/pipe_flow_paired_100_20261122/RESULT.md)。

[普通流体方腔OpenFOAM完整工程链](../../../../graduation-experiment-results/chapter3_end_to_end_evaluation/dsh/openfoam_cavity_solve_20261122_r2/RESULT.md)已由操作者工程验证建网、初始化、icoFoam时间推进与原生场回收，agent自主交付待单独评价。

[专业agent方腔修改交付](../../../../graduation-experiment-results/chapter3_end_to_end_evaluation/dsh/openfoam_cavity_agent50_20261122/RESULT.md)使用50次独立预算，经正常模型会话修改100单元方腔并完成真实OpenFOAM求解，45次请求后封存并可复跑摘要。

[方腔新变体双臂比较](../../../../graduation-experiment-results/chapter3_end_to_end_evaluation/dsh/openfoam_cavity_pair100_20261122/RESULT.md)事前固定每臂50次请求。两臂144单元真实求解均成功、最终场相同；原始臂40次完成交付，专业臂50次耗尽时缺README，完整交付为1/1对0/1。该公开开发单题不支持专业系统的稳定收益结论。

[两技能交付流程修订](../../../../graduation-experiment-results/chapter3_end_to_end_evaluation/dsh/openfoam_cavity_revision100_20261122/RESULT.md)在新参数配对中未改善完整交付，旧版与候选均0/1：旧版目录不合契约，候选重复哈希检查后仅提交原始备份。默认技能已恢复旧版，冻结候选、失败及监控更正完整保留。

[明确检查回执与重复动作控制](../../../../graduation-experiment-results/chapter3_end_to_end_evaluation/dsh/delivery_controls_offline_20261122/RESULT.md)已通过正常工具注册表的离线验收，默认关闭。`start.py` 加 `--delivery-controls` 可加载只读 `verify_artifact_manifest` 和连续三次相同成功shell结果后的派发阻断；`delivery-check` 为专用离线测试动作。它不生成交件，可能中断合法的重复轮询，尚无模型交付收益证据。离线入口临时配置目录现位于工作目录旁，满足Windows ACL runner的暂存路径要求。

[控制插件真实开关配对](../../../../graduation-experiment-results/chapter3_end_to_end_evaluation/dsh/delivery_controls_live100_20261122/RESULT.md)严格完整交付为开启0/1、关闭0/1，分别缺README和未保留两份上传输入的文本身份。两臂求解及正式摘要正确；新增工具实际调用0次、阻断0次，未观察到交付收益。另有受控合法状态变化探针确认误拦及恢复成本，候选继续默认关闭。

[七份方腔交件的契约与来源审计](../../../../graduation-experiment-results/chapter3_end_to_end_evaluation/dsh/delivery_contract_audit_20261122/REPORT.md)确认原工作区输入和打包路径保留，覆盖发生在模型交付副本；同时确认题面没有明示维护侧逐字文本要求，需作为解释限制。独立候选 `cavity_agent/contract_client.py` 将登记输入与原生回收哈希分开返回，旧wire format及一次登记约束不变，不生成交件；3项CLI测试和7份只读视图检查通过，尚未接入任务。历史判定不变，改变主要评价标准需另行决定。

[新公开契约的整体系统配对](../../../../graduation-experiment-results/chapter3_end_to_end_evaluation/dsh/delivery_contract_pair100_20261122/RESULT.md)通过 `cavity_agent/contract_pair_run.py` 在独立协议中将同一候选客户端和说明提供给原始／专业两臂，未替换默认client.py。完整交付0/1对1/1，共72请求、2节点17秒；原始臂含接口中断和未完成读出脚本，专业臂输入身份及README重建通过。保留未知用量与附加说明错误，不把结果当作客户端因果收益或未见任务成绩。

`startup_couette/run.py`通过显式发布快照及CURRENT哈希链采用COUETTE-START01公开包，准备两臂空工程；不发维护fixture或解析参考。`startup_couette/client.py`只在原客户端返回视图中补充profile.csv必需路径，登记字节及一次提交约束不变。4项相关CLI测试通过。[维护节点与派发准备证据](../../../../graduation-experiment-results/chapter3_end_to_end_evaluation/dsh/cross_family_preparation_20261122/RESULT.md)及[模型独立协议](../../../../graduation-experiment-results/chapter3_end_to_end_evaluation/dsh/startup_couette_pair100_20261122/protocol.json)分别归档。

[COUETTE-START01模型结果](../../../../graduation-experiment-results/chapter3_end_to_end_evaluation/dsh/startup_couette_pair100_20261122/RESULT.md)两臂均0/1；原始臂内存分配失败前未登记，专业臂真实节点缺pFinal退出并缺少读出／说明交件。94请求、1个模型作业失败5秒，维护作业另列。运行时版本元数据候选仅为下一公开接口的离线准备，未注入本批或证明收益。

[错误传递候选离线验收](../../../../graduation-experiment-results/chapter3_end_to_end_evaluation/dsh/error_propagation_offline_20261122/RESULT.md)：`shell-failure-propagation.mjs`通过官方执行后处理接口将前台shell非零退出等标为错误，保留原始诊断；上游原语义是有意设计，因此候选仅为可选严格策略。`run_shell_failure_probe.py <新目录>`完成原生注册表开关验证。`../model_budget_errors.py`提供显式HTTP候选入口，沿用原Gate记账而区分错误类别；不替换默认launcher、不重试或退预算。22项Python、10次实际命令及独立复核通过；不代表OOM解决或模型交付收益。

[宿主恢复与公开身份接口](../../../../graduation-experiment-results/chapter3_end_to_end_evaluation/dsh/host_recovery_offline_20261122/RESULT.md)：`host_recovery_probe.py <新目录>`顺序运行3次正常DSH启动与受控子进程并采样内存。`startup_couette/prepare_runtime_public.py <新目录>`只读核验归档身份，输出三文件公开包；`runtime_info.py --expected-sha256 <派发清单哈希>`读取运行时说明，不提交或补写工程。3次入口和4项CLI检查通过，短时低负载恢复仅支持有即时预检、持续监测及停止规则的条件性恢复；旧默认入口、题包和协议不变。

[显式集成入口](../../../../graduation-experiment-results/chapter3_end_to_end_evaluation/dsh/integrated_entry_offline_20261122/RESULT.md)最终candidate02将相同公开runtime、HTTP错误边界、严格shell策略和运行环境接入两臂；`../launch_integrated_attempt.py inspect --pair <准备目录> --arm <臂>`离线校验，`run`须额外绑定集成策略摘要并通过原授权检查。`prepare_integrated_entry.py`制备的授权明确禁止模型调用，`check_integrated_entry.py`只执行正常工具与本地假provider验收。`startup_couette/runtime_client.py`新增runtime动作，原submit/collect数据不变。独立审查通过；节点操作者和强制监测/连接停止守卫仍待新任务接入，不能将该接口夹具当成新付费协议。
