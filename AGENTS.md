# PrincipiaBlastFoam-DSH 贡献者说明

2026-11-05 SSH恢复：负责人授权单卡A100运行两个8B。经三模型接口及双8B的16/32并发合成检查后，已从暂停断点恢复；原35,171份终态文件核验保留。8B经本机18000/18001的SSH回环隧道调用，guidance、BF16、上下文32768；正式查询512、输出2048、题集200＋100及评分规则不变。当前生成入口为`execution_updates/fast_resume_20261105/resume_runner.py`，评分沿用双裁判8／8。SSH中断需要恢复通道；已有尝试次数不清零。以下为此前阶段记录。

2026-11-05当前状态：负责人为调试模型部署与镜像配置，已于北京时间2026-11-05 11:26:57暂停全部第2章实验。三模型生成、双裁判评分、监督和自动恢复进程均已停止，剩余进程0；派发授权关闭，禁止自动恢复。已有回答、评分及请求台账原样保留，题集200＋100、Gold和评分规则不变。须待负责人恢复指令及新服务配置核验后，按原尝试预算从断点继续。详见[暂停记录](D:/1/graduation-projects/graduation-experiment-results/chapter2_retrieval/FORMAL_PAUSE_20261105.md)。以下为此前阶段记录。

2026-11-05解码排查与评分提速：双裁判已从GPT／DeepSeek的2／1提高至8／8，提示、模型参数和评分规则不变。监督及评分活动入口改为`graduation-experiment-results/chapter2_retrieval/execution_updates/throughput_20261105/operations.py`，安全启动用同目录`start.ps1`；生成仍使用ce2155fd55fa补充，当前Qwen／14B／Llama并发16／20／32，8B自动降档与回升继续有效。Qwen延迟已定位到服务端解码，硬关闭思考的合成对照没有消除差距，正式推理请求未改变。本次交接前29,315份终态文件逐一核验未改。详见[最新排查记录](D:/1/graduation-projects/graduation-experiment-results/chapter2_retrieval/REDEPLOYMENT_RESUME_20261105.md)。以下为此前阶段记录。

2026-11-05重新部署后已恢复：两个8B的新URL已通过单步/多轮接口及16/32并发长输入检查，以Qwen3-8B／Qwen3-14B／Llama-3.1-8B并发32／20／32启动，实际并发及临时降档见运行状态。新执行补充ce2155fd55fa沿用原方法协议95a4872aacdd，保留全部旧回答、评分及台账。活动入口为`graduation-experiment-results/chapter2_retrieval/execution_updates/redeploy_20261105/redeploy_runner.py`；安全启动用同目录start.ps1。详见[恢复报告](D:/1/graduation-projects/graduation-experiment-results/chapter2_retrieval/REDEPLOYMENT_RESUME_20261105.md)。下文为此前阶段记录。

2026-11-05暂停：负责人因重新部署两个8B推理服务，要求暂时停止全部实验。三模型生成、双裁判评分和监督进程均已停止，生成与评分授权已关闭，禁止自动恢复。已有回答、评分及请求台账保留；以`release/planning/formal_pause.json`和[暂停记录](D:/1/graduation-projects/graduation-experiment-results/chapter2_retrieval/FORMAL_PAUSE_20261105.md)为当前状态。服务部署完成后，先核验模型、接口及并发并取得恢复指令，再记录执行补充并断点继续。以下为此前运行记录。

2026-11-05执行更新：14B已恢复；两个8B从8提高到16并发，并按成功请求观察自动尝试32，遇连续传输错误会降档。正式方法协议95a4872aacdd、题目、Gold及评分不变；执行补充c0d6407fa327记录传输错误映射和调度变更。当前监督与恢复入口为`graduation-experiment-results/chapter2_retrieval/execution_updates/speedup_20261105/runner.py supervise`，启动环境需包含`PrincipiaBlastFoam-DSH/experiments/retrieval_method`的PYTHONPATH。具体检查和运行状态见[执行更新报告](D:/1/graduation-projects/graduation-experiment-results/chapter2_retrieval/EXECUTION_UPDATE_20261105.md)。以下为原启动记录。

2026-11-04最新决定：额外60份人工验收已取消，以现有60份人工参考及双裁判校准结果采用现有双裁判方法。客观200＋开放100、分类配额和Gold不变；正式协议与技术核验已完成，三模型全量生成及双裁判评分已在后台启动（协议95a4872aacdd）。唯一活动运行入口为`PrincipiaBlastFoam-DSH/experiments/chapter2/formal_experiment.py`，授权与状态见实验`release/planning/formal_experiment.json`及`formal_execution.json`。不重做人工评分或校准，不把旧验收门槛作为派发条件。以下早期阶段说明保留历史身份。

2026-11-04当前进展：开放问答本轮60份人工参考评分已完成（AI建议、真人逐项复核确认、助手转录），客观题200道参考答案已由负责人审核通过。已完成两个AI裁判及逐答均值与人工参考的校准比较；裁判输出失败、人工Unknown及完整分母均保留。这是校准诊断，不是独立人评或验收通过；验收仍锁定，规则尚未为验收冻结，全量未启动。报告见`graduation-datasets/chapter02_knowledge_qa/open/review/calibration/ai_calibration/85b246b6f258/REPORT.md`。

以下生成/准备阶段状态保留其历史身份；当前完成范围以上述进展为准。

## 目录职责

- `.dsh/skills/`：供模型读取的 blastFoam 操作规程。Skill 名称保持 kebab-case，每个 Skill 只使用一个直接入口 `<name>/SKILL.md`。
- `packages/principia-dsh-bundle/`：可安装的 DSH bundle，包含策略插件、角色专属 subagent 工具行和 MCP 客户端配置。
- `src/principia_core/`：不依赖智能体框架的 Python 领域服务。
- `mcp_servers/`：领域服务之上的 MCP 协议适配层。
- `deployment/dsh/`：只提交配置模板；机器路径、profile 状态、API Key 和其他凭据均放在 Git 之外。
- `compatibility/`：经过验证的 DSH commit、包版本和升级证据。
- `experiments/`：评测适配器与评测方法文档；正式实验结果仍写入外部毕业实验归档目录。

## 不可破坏的约束

- 保持 DSH bundle 与 profile 分离：`dsh.bundle` 属于可安装包，profile manifest 由 DSH 创建和管理。
- 精确固定预发布 DSH 包版本，不使用 `latest`、脱字符范围或未验证的版本范围。
- profile patch 会替换目标条目的完整 `config`，因此必须重新声明所有必需字段。
- 复用官方 `spawn` subagent provider，不注册同名的第二个进程级 provider。
- 确定性领域逻辑和产物验证必须放在提示词之外；提示词只能引导行为，不能充当强制约束。
- 不得提交凭据或机器特定的绝对路径。
- 除非是明确需要版本控制的测试夹具，否则生成算例、日志、报告、benchmark 结果、缓存和 DSH profile 状态均不得进入源码仓库。
- 项目文档以中文为主体；命令、环境变量、协议字段、代码标识符和上游包名保留英文。
- 第2章自研最终检索实现必须是仅依赖持久化图和原始语料的免外部索引方法；不得依赖 E5、BM25、向量库、倒排索引或预计算 passage embedding。查询时可直接扫描图节点/边的标签、别名、作用域和来源路径，再回原始文件核验证据。
- 不得将 Graphify text-adapter 的 `.txt` 副本作为自研构图输入或权威来源。该适配只用于公平测量 Graphify 对无后缀 OpenFOAM 文件的摄取能力，必须保留原路径映射，并在查询输出和引用中恢复原始路径。
- 第2章检索质量横向比较必须先映射到统一权威证据层，不得直接比较 BM25/E5 chunk、Graphify 节点、自研图节点、文件或章节的原生 Recall/MRR。`canonical_evidence_v1` 至少保留原始路径与哈希、精确行段、来源/作用域、原生单元与排名、去重首次排名、累计返回字符和查询耗时。
- 历史检索计划与正式固定查询分开：当前固定查询按2000/4000/6000实际序列化字符、11种检索配置执行，汇总见current/retrieval-summary.json；只报告实际计算且定义清楚的指标，未实现的nDCG不得虚报。Hit Rate 仅作辅助。当前 gold 非穷尽相关性池，Precision@K 只能报告为“必要 gold 精度下界”。
- 历史多步回答轨迹只能评价实际送达回答模型的原文证据，不能冒充单轮检索器排名。正式检索比较必须由各后端导出原生排名后再统一映射，且必须测试 chunk 跨多个证据、多个节点映射同证据、重复证据、预算截断和多来源完整召回。
- 历史会话的首次 `search/locate` 返回可统一映射到权威文件层，作为 `whole-system first-call` 诊断；它仍继承各臂模型生成查询的差异，不能称为公共查询规划器下的纯后端榜。不可映射的图片、二进制或清单外路径须保留排名惩罚，禁止删除后重排。
- 旧开发轮次的 post-hoc 指标保持历史身份，不替换其预注册结论。当前40题测试身份固定，不按其结果调参；gold 仅供评测，不进入生产输入或技能学习。冻结实验产物不可覆盖，派生报告须保留输入哈希和解释边界。

## 当前论文与实验入口


研究目标与章节边界先读 [共享设计入口](../graduation-thesis-materials/graduation-research/README.md)及[总体设计](../graduation-thesis-materials/graduation-research/OVERVIEW.md)，按任务引用[第2章](../graduation-thesis-materials/graduation-research/chapters/chapter02.md)、[第3章](../graduation-thesis-materials/graduation-research/chapters/chapter03.md)或[第4章](../graduation-thesis-materials/graduation-research/chapters/chapter04.md)。详细工程计划仍在本仓库维护，不复制一套章节设计。共享设计中的目标不能视为实现已完成或效果已验证，冻结实验结论以原协议和证据为准。

本仓库是当前应用唯一开发入口，第3章与第4章基于DSH。

## 验证要求

至少运行 bundle 检查、Python 测试、profile `--dump-config`、MCP 状态冒烟测试和相关 benchmark 用例。升级 DSH 后，只有通过兼容性验收矩阵，才能更新 `compatibility/dsh-version.json`。

## 第4章研究边界（2026-10-04用户修正）

第4章独立研究RSI，默认仅一个agent，DSH只作为开发框架。不得继承第3章协调者、五专家角色、阶段编排、七项产物契约或预设轨迹来源。同一agent执行任务并提出自身改进，接受后的版本继续下一轮；确定性验证与统计脚本不算额外agent。独立profile与配置不得加载第3章多角色bundle。现阶段只有研究设计，没有RSI收益结果。



## 第2章当前维护约束（2026-11-03）

生成恢复阶段快照（早于人工评分与AI校准）：已实现并应用自动传输重试。每请求最多3次尝试，单次600秒，退避5秒/15秒；只重试超时、连接中断、HTTP 408/429/5xx及进程中断，不根据回答内容重试。原16条传输问题按独立执行补充协议恢复，原44份回答未重跑或改动。当前60任务为59份完整回答、1条模型输出失败、0条传输未解决；校准任务结果齐备、待人工评分。查询512、输出2048、题集100＋200及Gold/binding不变。全部派发已关闭，验收、全量与AI裁判未启动，真人标签为空。

当前推理协议`d658134e6df5053454ed78893523eb25320d8354dec558f689d4dacc4524ccf2`保持不变，传输执行补充为`a1d2e3a24d9c5c2d7f36263c2805eb2459b22b1ef75f41d0890e84765d47a871`；源码改变由补充清单核验，不覆盖原冻结源码。后续维护补齐技术错误映射和准备保护，新的正式派发须重新prepare；已运行结果按执行时冻结源码核验。当前匿名表与报告在数据集open/review/calibration/，核验用tools/verify_transport_recovery.py --binding；tools/verify_generation.py --binding自动转到当前恢复核验。旧44＋16待处理阶段及此前55＋5批次均保留为历史，禁止混用其答案。详见GENERATION_REPORT.md与TRANSPORT_RETRY_REPORT.md。

客观题200道与开放问答100道为同等级的两个部分，全量参加评价，不另设开发集或测试留出集。客观题fill60/short60/single50/judge30，开放S0/S1/M0/M1各25；开放覆盖69主题、24知识组、42来源文件与8组成对条件题。

Qwen3-8B、Qwen3-14B与Llama-3.1-8B-Instruct均覆盖单步回答和多步自主取证，三模型可通过各自服务并行调度；所有题型共用该模型的并发限额。

当前尚无新正式实验成绩；已确认6k/12k/24k三档证据预算、单人60份校准＋60份锁定验收。运行器、分词器和合成接口检查属于准备工作，正式批量仍未获本轮启动授权，真人评分及裁判验收尚未完成。负责人已确认资源充足，不设置费用审批或费用上限。当前题集有方法开发使用经历，不能宣称为历史未见的独立测试。Gold、authoring、review和人工记录仅限评分或维护侧。

旧题、旧结果及恢复链已获授权清理；当前输入独立维护。私有配置不得输出。运行准备使用experiments/chapter2/runner.py和已绑定的三个模型分词器；实际人工表在数据集open/review/calibration/。当前校准生成和传输恢复已完成；全量与裁判批量仍未启动。
