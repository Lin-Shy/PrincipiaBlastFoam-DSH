# 第2章全量运行实现

2026-11-05 SSH恢复：负责人授权单卡A100运行两个8B。经三模型接口及双8B的16/32并发合成检查后，已从暂停断点恢复；原35,171份终态文件核验保留。8B经本机18000/18001的SSH回环隧道调用，guidance、BF16、上下文32768；正式查询512、输出2048、题集200＋100及评分规则不变。当前生成入口为`execution_updates/fast_resume_20261105/resume_runner.py`，评分沿用双裁判8／8。SSH中断需要恢复通道；已有尝试次数不清零。以下为此前阶段记录。

2026-11-05当前状态：负责人为调试模型部署与镜像配置，已于北京时间2026-11-05 11:26:57暂停全部第2章实验。三模型生成、双裁判评分、监督和自动恢复进程均已停止，剩余进程0；派发授权关闭，禁止自动恢复。已有回答、评分及请求台账原样保留，题集200＋100、Gold和评分规则不变。须待负责人恢复指令及新服务配置核验后，按原尝试预算从断点继续。详见[暂停记录](D:/1/graduation-projects/graduation-experiment-results/chapter2_retrieval/FORMAL_PAUSE_20261105.md)。以下为此前阶段记录。

2026-11-05解码排查与评分提速：双裁判已从GPT／DeepSeek的2／1提高至8／8，提示、模型参数和评分规则不变。监督及评分活动入口改为`graduation-experiment-results/chapter2_retrieval/execution_updates/throughput_20261105/operations.py`，安全启动用同目录`start.ps1`；生成仍使用ce2155fd55fa补充，当前Qwen／14B／Llama并发16／20／32，8B自动降档与回升继续有效。Qwen延迟已定位到服务端解码，硬关闭思考的合成对照没有消除差距，正式推理请求未改变。本次交接前29,315份终态文件逐一核验未改。详见[最新排查记录](D:/1/graduation-projects/graduation-experiment-results/chapter2_retrieval/REDEPLOYMENT_RESUME_20261105.md)。以下为此前阶段记录。

2026-11-05重新部署后已恢复：两个8B的新URL已通过单步/多轮接口及16/32并发长输入检查，以Qwen3-8B／Qwen3-14B／Llama-3.1-8B并发32／20／32启动，实际并发及临时降档见运行状态。新执行补充ce2155fd55fa沿用原方法协议95a4872aacdd，保留全部旧回答、评分及台账。活动入口为`graduation-experiment-results/chapter2_retrieval/execution_updates/redeploy_20261105/redeploy_runner.py`；安全启动用同目录start.ps1。详见[恢复报告](D:/1/graduation-projects/graduation-experiment-results/chapter2_retrieval/REDEPLOYMENT_RESUME_20261105.md)。下文为此前阶段记录。

2026-11-05暂停：负责人因重新部署两个8B推理服务，要求暂时停止全部实验。三模型生成、双裁判评分和监督进程均已停止，生成与评分授权已关闭，禁止自动恢复。已有回答、评分及请求台账保留；以`release/planning/formal_pause.json`和[暂停记录](D:/1/graduation-projects/graduation-experiment-results/chapter2_retrieval/FORMAL_PAUSE_20261105.md)为当前状态。服务部署完成后，先核验模型、接口及并发并取得恢复指令，再记录执行补充并断点继续。以下为此前运行记录。

2026-11-05执行更新：14B已恢复；两个8B从8提高到16并发，并按成功请求观察自动尝试32，遇连续传输错误会降档。正式方法协议95a4872aacdd、题目、Gold及评分不变；执行补充c0d6407fa327记录传输错误映射和调度变更。当前监督与恢复入口为`graduation-experiment-results/chapter2_retrieval/execution_updates/speedup_20261105/runner.py supervise`，启动环境需包含`PrincipiaBlastFoam-DSH/experiments/retrieval_method`的PYTHONPATH。具体检查和运行状态见[执行更新报告](D:/1/graduation-projects/graduation-experiment-results/chapter2_retrieval/EXECUTION_UPDATE_20261105.md)。以下为原启动记录。

当前已完成冻结与核验，三模型全量生成和评分已在后台启动。启动及检查记录见[FORMAL_RUN_REPORT.md](D:/1/graduation-projects/graduation-experiment-results/chapter2_retrieval/FORMAL_RUN_REPORT.md)。

2026-11-04：负责人取消额外60份验收，采用现有60份人工参考及双裁判校准结果，授权技术核验通过后直接启动三模型全量。当前题目、Gold、人工评分及裁判提示和规则保持不变。

正式题集为客观200＋开放100，不设开发集。171配置、51,300项逻辑任务；客观34,200、开放17,100。三模型独立并行，两个8B各8并发、14B为20，同模型全部题型共享限额。单步/多步均覆盖两类题，证据预算6k/12k/24k，M为主比较，全部报告。回答查询512字符、输出2048 tokens；双裁判输出8192（含思考）、输入24576。

现有60项校准回答经实际生成依赖、分词器、服务和资源等价性核验后完整采用，包括1项生成失败；既有裁判输出不合规及传输未知也原样保留。剩余51,240项生成。原验收任务回归普通全量，不额外要求人评。

## 运行与核验

- 唯一正式入口：`PrincipiaBlastFoam-DSH/experiments/chapter2/formal_experiment.py`。
- 正式协议与冻结实现：`release/planning/formal_experiment.json`指向`release/frozen/formal_experiment/`。
- 正式授权：`release/planning/formal_execution.json`；只有对应协议的技术核验通过后才启用。
- 全量生成、评分、进度及日志：指针中的`formal/<协议前缀>/`。`supervisor.json`记录后台进程，`generation/<模型>/progress.json`及`scoring_progress.json`记录进度。
- `formal_experiment.py verify`核对当前冻结；`status`只读状态；`supervise`运行生成和评分；重新启动`supervise`恢复同一协议，不重新freeze。

每请求最多3次尝试，600秒，退避5/15秒；仅传输超时/中断、408/429/5xx及进程中断重试。已收到响应不按内容重试；进程恢复重放已保存响应，尝试计数不清零，已完成任务跳过。单任务耗尽记未知并继续其他任务；身份、分词器、配置或持久化异常停止相关服务并保留现场。监督进程自动重启意外退出的工作进程，明确的致命错误不无限重启。

生成与评分分别运行。生成端只读公开题干和知识资源，禁止Gold、authoring、review和人工记录。客观题程序只评显式final_answer；开放题沿用两个裁判独立评分及逐答均值，保留EAS_arith、EAS_geo和Strict。失败、未知、未运行分开，所有统计保留固定分母，既有回答不择优替换。

## 校准与历史证据

运行前检查包括58项Python测试、bundle检查、profile配置导出、MCP状态冒烟及合成接口核验，回执进入实验归档。

现有校准报告与人工参考在`graduation-datasets/chapter02_knowledge_qa/open/review/calibration/`；题目及Gold不变。额外验收的旧空白材料仅保留历史身份，禁止旧`freeze-acceptance`和旧分阶段派发重新打开。旧生成、传输恢复、校准协议均不覆盖；新正式协议保存实际采用清单、等价性依据和来源哈希。

本次采用校准结果是负责人的方法使用决定，不将其改写成原目标全部达成或额外验收通过。完整实测数字及校准讨论保持原样；不再把人工评分过程作为待处理事项。
