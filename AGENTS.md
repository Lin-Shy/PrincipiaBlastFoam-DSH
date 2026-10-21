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
- 第2章模型与部署以各冻结协议为准。合成行为控制已通过，独立人工校准仍pending；生成与评分已闭合4600会话，32B无结果。
- 第2章检索质量横向比较必须先映射到统一权威证据层，不得直接比较 BM25/E5 chunk、Graphify 节点、自研图节点、文件或章节的原生 Recall/MRR。`canonical_evidence_v1` 至少保留原始路径与哈希、精确行段、来源/作用域、原生单元与排名、去重首次排名、累计返回字符和查询耗时。
- 历史检索计划与正式固定查询分开：当前固定查询按2000/4000/6000实际序列化字符、11种检索配置执行，汇总见current/retrieval-summary.json；只报告实际计算且定义清楚的指标，未实现的nDCG不得虚报。Hit Rate 仅作辅助。当前 gold 非穷尽相关性池，Precision@K 只能报告为“必要 gold 精度下界”。
- 历史多步回答轨迹只能评价实际送达回答模型的原文证据，不能冒充单轮检索器排名。正式检索比较必须由各后端导出原生排名后再统一映射，且必须测试 chunk 跨多个证据、多个节点映射同证据、重复证据、预算截断和多来源完整召回。
- 历史会话的首次 `search/locate` 返回可统一映射到权威文件层，作为 `whole-system first-call` 诊断；它仍继承各臂模型生成查询的差异，不能称为公共查询规划器下的纯后端榜。不可映射的图片、二进制或清单外路径须保留排名惩罚，禁止删除后重排。
- 旧开发轮次的 post-hoc 指标保持历史身份，不替换其预注册结论。当前40题测试身份固定，不按其结果调参；gold 仅供评测，不进入生产输入或技能学习。冻结实验产物不可覆盖，派生报告须保留输入哈希和解释边界。

## 当前论文与实验入口

当前Qwen接入（2026-10-21）：按需要显式选择模型，两者均可用于任意任务规模，统一使用32K（32768 tokens，输入＋输出）额度。本地`Qwen3-8B`端口8001，并发上限8；代理`qwen3-14b`并发上限20。接入与实测见[Qwen说明](../QWEN_MODEL_ROUTING.md)。正式实验沿用各自冻结协议。

研究目标与章节边界先读 [共享设计入口](../graduation-thesis-materials/graduation-research/README.md)及[总体设计](../graduation-thesis-materials/graduation-research/OVERVIEW.md)，按任务引用[第2章](../graduation-thesis-materials/graduation-research/chapters/chapter02.md)、[第3章](../graduation-thesis-materials/graduation-research/chapters/chapter03.md)或[第4章](../graduation-thesis-materials/graduation-research/chapters/chapter04.md)。详细工程计划仍在本仓库维护，不复制一套章节设计。共享设计中的目标不能视为实现已完成或效果已验证，冻结实验结论以原协议和证据为准。

本仓库是当前应用唯一开发入口，第3章与第4章基于DSH。

## 第2章当前状态（2026-10-20统一维护）

- 原200题、69主题、24知识组及评分标注保持不变，全部问题已人工审核。活动题集实体为`graduation-datasets/chapter02_knowledge_qa/development_v1_160/`与`test_v1_40/`，各自维护model/与scoring/；formal_v2_200仅作原件。
- 原160题用于开发调参，原补充40题为从未参与调参的未见留出集；依据研究者对未同步记录的更正确认，沿用已有ID与调参设置，不补造冻结时间，不重新选题。测试14主题、5知识组、四类7/6/20/7，开发四类43/44/30/43；不宣称测试均衡或未见文档。
- 当前结果统一由`graduation-experiment-results/chapter2_retrieval/current/results.json`管理；实体在`current/qwen3-8b/`和`current/qwen3-14b/`各自的development/与test/下，按方法/original或replicate/题目ID存放生成与评分。旧独立分集目录仅保留历史统计与迁移说明。
- 主比较统一九种方法：完整图、BM25、E5 Dense、BGE-M3 Dense、BM25+E5、BM25+BGE-M3、BM25父上下文、基础搜索、模型直接作答。消融四项：去来源关联、去中文别名、关闭关系遍历、仅锚点。E5和BGE同时保留；新Embedding仅BGE-M3 Dense。
- 历史生成和评分已闭合4600会话；指定完整图/BM25重跑400会话原始文件按用户最新选择删除后，当前保留4200会话（开发3360、测试840），其中8B1600、14B2600。8B只运行原六方法/两消融，不伪造其新增方法结果。32B无结果，等待API及另行协议和预算。
- 用户最新选择为完整图/BM25仅用原运行，E5与BGE保留。新增五项的公共逐行去重消费者存在差异；仅列原5主比较/2消融，遍历/锚点缺少保留的同协议参照，仅作描述，不重建已删除比较。40题5知识组比较均未达保守校正显著性，不能沿用全200题24组结论。
- 题目审核与独立评价核验分开。用户已确认AI裁判人评和来源图质量抽查尚未完成，保持pending；80份匿名回答需两位评审各80条标签，图抽查50节点/50关系/30别名。不能用合成控制代替人评准确率。
- Gold、必要点、权重、证据和人评表仅限评分侧；不进入构图、索引、检索、回答或学习输入。原始题目、图、语料、生成、评分及冻结协议不改，失败0分、未知保留边界。拒绝的新40/60题草稿已清理，不再新建题目。

实施见[工程计划](experiments/retrieval_method/KNOWLEDGE_QA_PLAN.md)，实际状态与批次入口见[实验总入口](../graduation-experiment-results/chapter2_retrieval/current/README.md)。正式图已获接受，不再择图；基础搜索仅提供glob/grep/原文读取，模型直接作答无工具，其他检索组各用专用后端。原8B基线复用及新增对照另批身份不得改写。论文已同步，答辩待同步，第4章仍无RSI收益结果。

## 验证要求

至少运行 bundle 检查、Python 测试、profile `--dump-config`、MCP 状态冒烟测试和相关 benchmark 用例。升级 DSH 后，只有通过兼容性验收矩阵，才能更新 `compatibility/dsh-version.json`。

## 第4章研究边界（2026-10-04用户修正）

第4章独立研究RSI，默认仅一个agent，DSH只作为开发框架。不得继承第3章协调者、五专家角色、阶段编排、七项产物契约或预设轨迹来源。同一agent执行任务并提出自身改进，接受后的版本继续下一轮；确定性验证与统计脚本不算额外agent。独立profile与配置不得加载第3章多角色bundle。现阶段只有研究设计，没有RSI收益结果。
