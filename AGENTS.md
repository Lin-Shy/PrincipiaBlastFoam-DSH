# PrincipiaBlastFoam-DSH 贡献者说明

本仓库是 PrincipiaBlastFoam 基于 DeepSeek Harness 实现的独立应用源码。DeepSeek Harness 只是上游运行时依赖；不得在上游 DSH 检出目录中实现 Principia 业务功能。

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
- 第2章离线构图、语义生成与离线校验使用精确 `deepseek-flash`；在线两模型比较使用各活动冻结的精确 `qwen3-8b` 和 `qwen3-14b`，固定v7正式裁判为 `qwen3-14b`。批量读取 `.env.qwen_proxy`，每模型最多16并发且不能叠加控制器；小批量本地按 `QWEN_LOCAL_MODELS.md` 和 `.env.qwen_local` 单独记录部署。已有冻结活动不改写。
- 第2章检索质量横向比较必须先映射到统一权威证据层，不得直接比较 BM25/E5 chunk、Graphify 节点、自研图节点、文件或章节的原生 Recall/MRR。`canonical_evidence_v1` 至少保留原始路径与哈希、精确行段、来源/作用域、原生单元与排名、去重首次排名、累计返回字符和查询耗时。
- 检索-only主指标使用 Recall@1/3/5/10、Complete Evidence Set Success@5/10、MRR、nDCG@10，并同时给出 6000/12000/24000 返回字符预算下的证据召回；Hit Rate 仅作辅助。当前 gold 非穷尽相关性池，Precision@K 只能报告为“必要 gold 精度下界”。
- 历史多步回答轨迹只能评价实际送达回答模型的原文证据，不能冒充单轮检索器排名。正式检索比较必须由各后端导出原生排名后再统一映射，且必须测试 chunk 跨多个证据、多个节点映射同证据、重复证据、预算截断和多来源完整召回。
- 历史会话的首次 `search/locate` 返回可统一映射到权威文件层，作为 `whole-system first-call` 诊断；它仍继承各臂模型生成查询的差异，不能称为公共查询规划器下的纯后端榜。不可映射的图片、二进制或清单外路径须保留排名惩罚，禁止删除后重排。
- 旧开发轮次的 post-hoc 指标保持历史身份，不替换其预注册结论。留出集不锁定，可按新协议评测；gold 仅供评测，不进入生产输入或技能学习。冻结实验产物不可覆盖，派生报告须保留输入哈希和解释边界。

## 当前论文与实验入口

研究目标与章节边界先读 [共享设计入口](../graduation-research/README.md)及[总体设计](../graduation-research/OVERVIEW.md)，按任务引用[第2章](../graduation-research/chapters/chapter02.md)、[第3章](../graduation-research/chapters/chapter03.md)或[第4章](../graduation-research/chapters/chapter04.md)。详细工程计划仍在本仓库维护，不复制一套章节设计。共享设计中的目标不能视为实现已完成或效果已验证，冻结实验结论以原协议和证据为准。

本仓库是当前多智能体应用的唯一开发入口，第3章与后续第4章基于 DSH。第2章唯一题集为 `../graduation-datasets/chapter02_knowledge_qa/formal_v1/` 的277题，开发77题/5知识组、测试200题/15知识组。同一题集的基准图比较、图匹配诊断和父内容策略比较分别归档于 `knowledge_qa_20261013/`、`knowledge_qa_optimization_20261016/` 和 `knowledge_qa_full_20261017/`，三者均位于外部 `chapter2_retrieval/`，不代表不同题集；其他题集及其实验文件已按用户要求清理。论文正文与最终图表仅在 `../graduation-manuscript/` 维护。第4章设计见 `experiments/self_evolution/PLAN.md`，目前没有 DSH 自进化正式结果。

## 验证要求

至少运行 bundle 检查、Python 测试、profile `--dump-config`、MCP 状态冒烟测试和相关 benchmark 用例。升级 DSH 后，只有通过兼容性验收矩阵，才能更新 `compatibility/dsh-version.json`。

## 第4章研究边界（2026-10-04用户修正）

第4章独立研究RSI，默认仅一个agent，DSH只作为开发框架。不得继承第3章协调者、五专家角色、阶段编排、七项产物契约或预设轨迹来源。同一agent执行任务并提出自身改进，接受后的版本继续下一轮；确定性验证与统计脚本不算额外agent。独立profile与配置不得加载第3章多角色bundle。现阶段只有研究设计，没有RSI收益结果。
