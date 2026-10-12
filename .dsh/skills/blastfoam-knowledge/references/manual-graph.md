# 章节与原文证据图

新手册直接读取 `corpus/manual/markdown/*.md`，插图读取相对 `figures/` 路径。不要恢复已移除的分页文本、PDF 转写或视觉试抽流程，也不要覆盖用户提供的 Markdown。

## 定位与证据边界

图谱是关键词检索的预算内补充：关键词负责直接匹配，章节结构组织完整证据，审核后的语义关系提示关联定义、组合限制及跨节依赖。三者共同服务有出处的回答。关系数量、图的规模或可视化连通性本身不是收益指标。

当前冻结评测快照覆盖全书 21 份 Markdown、249 个章节节点、446 个原文证据节点及 21 个插图节点；经审核接受的 87 条语义事实来自第 5、7、9、19 章。不能将“全书基础图已构建”描述为“全书语义已抽取”。这些数字描述实验快照，新增语料后应重新检查，不替代实际索引状态。

既有 24 题自主探索中，语义工具可用组严格成功 23/24、关键词组 20/24，但没有实际关系或邻居调用；导航提示试验也只有一次空关系返回。因此观察到的答案分数差异不能证明语义边起效。新的[补充检索消融](../../../../experiments/retrieval_method/manual-complement.md)把关系直接放入同一搜索入口，并单独对照历史整理；该入口仍属开发验证，未接入生产 MCP。后续 32 会话中，两种图谱配置各有 7/8 会话收到关系，5 个会话引用了同查询关键词未返回的关联目标原文；说明补充证据能进入回答。完整历史下关键词严格成功 6/8、图谱 5/8，共同成功 4 题的平均累计 Token 下降 7.5%；历史整理下关键词 2/8、图谱 5/8，但共同成功仅 2 题且图谱成本更高。两组均未通过冻结门槛。M07 的默认 none 补充来自显式章节引用，还需与仅结构引用补充分离，不能全部归于模型抽取的语义边。以上为已有开发题单次采样、Codex 审阅，不是独立专家盲测。是否扩大语义范围，应依据实际条件关系使用、质量不下降及累计成本收益，不能仅凭格式合格或关系命中决定。

后续[显式引用与语义增量消融](../../../../experiments/retrieval_method/manual-attribution.md)重新运行三组共 24 会话：关键词 6/8、引用 4/8、引用加非 REFERENCES 语义 5/8 严格成功。语义相对引用在共同成功 3 题上节省 18.6% Token，但未满足至少 4 题的冻结门槛。M07 的默认 none 在两种补充组中均由显式引用找到，最终答案却一错一对；M01 则确认非引用语义更早带入 eConst。需要区分证据定位与答案使用，不以单题答对归因于新增语义。结果仍属开发诊断，下一步优先核对已见证据、条件和冲突，再用新题复验增量收益。

Graphify [v4 基准实现](https://raw.githubusercontent.com/Graphify-Labs/graphify/v4/graphify/benchmark.py)以估算的全语料 Token 除以局部节点/边上下文 Token；[71.5 倍示例](https://github.com/safishamsi/graphify/blob/v4/README.zh-CN.md)不包含本项目所要求的同题关键词基线、多步 API 消耗与答案质量验证。本项目分别报告上下文字符预算、累计 API 输入/输出 Token、探索步数、严格答案成功及共同成功题的成本；图谱构建与审核成本另计。减少上下文是方法目标，端到端节省必须实测。

## 构建与检查

从 skill 根目录执行，生成产物放在外部实验归档目录：

```bash
python scripts/manual_graph.py build --output <归档目录>/foundation/graph.json
python scripts/manual_graph.py check --output <归档目录>/foundation/graph.json
python scripts/build.py
python scripts/validate.py
```

独立手册图有 document、section、evidence 和 figure 四类节点。按真实标题维护父子层级，区分本节直接正文范围与整个子树范围。短小节整体保存，长小节按语义块拆分；公式的引导句、编号、连续表达式与 where 解释绑定，表格和代码块不按长度切开。构建检查逐字重组全部源文件、哈希、来源范围、唯一 ID、连接端点和图片路径。它证明组织过程保真，不证明转化结果或原文中的物理公式正确。

显式引用支持 Sec./Secs./Section/Sections/Chapter、Eq./Eqs./Equation/Equations、数字章号、小节号及逗号/and并列引用，并保留原文和行号。代码块、显示公式、内联代码和数学中的类似字符串不产生引用边；普通年份不当成公式编号。无法唯一解析的引用记录在 warnings，不猜测目标。数字区间引用暂未展开。

`knowledge.py` 的结构索引使用相同解析器，手册内容节点为 `manual_evidence`。`evidence_bundle.py` 复用这些完整单元，并把教程的定义引用限定到实际来源范围。通用图中保留 `DOCUMENTED_ON` 关系名以兼容现有导航协议，该关系现在连接章节与原文单元。

## 分章语义提取

```bash
python scripts/manual_semantic.py prepare --foundation <归档目录>/foundation/graph.json --run-dir <归档目录>/chapter5 --prompt references/manual-constraints-prompt.md
python scripts/manual_semantic.py extract --foundation <归档目录>/foundation/graph.json --run-dir <归档目录>/chapter5 --prompt references/manual-constraints-prompt.md --key-file <本地密钥文件> --workers 4
```

默认处理 `05_fluid_solid_thermo.md`，模型固定为精确名称 `deepseek-flash`；可以用 `--chapter <Markdown文件名>` 改变章节。模型标识参与计划、缓存键和响应校验，旧模型响应不能混入新计划。`--global-catalog` 提供全书章节ID以便模型将明示名称定位到定义小节，不扩大当批待抽取范围，也不注入评测题目或答案。

批次按完整小节组合，提供祖先正文和可解析的明示引用上下文。冻结源图、章节范围、提示、模型配置及每个请求哈希，原始响应和用量落在 run-dir。失败传输可续跑；已收到的响应即使格式或语义不满意也不重复采样。改变提示进行方法迭代时使用新的 run-dir，保留之前的结果和成本。方法迭代应比较关系方向、必需/可选强度、作用域与关键条件遗漏，不能只比较数量或格式通过率。

优先使用条件提示 `manual-constraints-prompt.md`：参数表已经在证据层可读，语义层侧重限制、输入关系、组合及跨节引用。通用提示 `manual-semantic-prompt.md` 保留用于复现首轮参数型抽取。

`semantic.json` 的事实绑定原文引句、主体/客体作用域、条件及处理记录。实体按类别、原文名、章节作用域识别，暂不自动合并别名。`source_checked_semantic_unreviewed` 只代表引句能定位。审阅记录单独保存为 review.json，包含 semantic_snapshot 和逐条 decisions（fact、accept/reject、reason），可以增加同节 additional_source_units 补充默认值的参数表依据；不改写原始响应。批次完整、出处完整、语义审核完整是不同状态。

若只改进显式引用规则，可以运行 `rebase_manual_semantic.py --old-foundation <旧基础图> --foundation <新基础图> --semantic <原语义图> --review <原审核记录> --output <新的归档子目录>`。脚本要求来源清单、所有节点及非引用边完全不变，核对快照后保留事实及审核，仅更新关联快照和追溯记录，不调用API。原文、切分或语义关系有变化时不能用此入口绕过重新提取/复核。

## 检索与可视化

```bash
python scripts/manual_search.py --foundation <归档目录>/foundation/graph.json --semantic <归档目录>/semantic/semantic.json --review <归档目录>/semantic/review.json --query "DoanNickel thermodynamic model parameters restrictions" --strategy semantic --budget 4500 --audit <归档目录>/query.json
python scripts/export_manual_graph.py --foundation <归档目录>/foundation/graph.json --semantic <归档目录>/semantic/semantic.json --review <归档目录>/semantic/review.json --output <归档目录>/viewer --katex-dist <本地KaTeX发行目录>/dist
```

检索的 `text`、`sections`、`semantic` 三组共用 BM25、证据单元、去重和 Markdown 打包。后两组先模拟同预算词法包，优先装入约60%预算内可完整容纳的词法单元，并保护查询明确点名的小节以及某个查询词唯一命中的来源；保护集合都来自已可装入的词法包，额外保护可能超过60%。只在剩余预算中从前三个已保护种子分别补充最多两个单元，最后用其余词法结果填充。

章节组先使用同节原文和明示引用，再考虑父节上下文；语义组使用命中实体的一跳关系及定义作用域。返回审计中的 protected_lexical 必须全部保留。词法词项保护是一种通用启发式，不保证语义上的所有子问题都已覆盖，也不保证所有预算下都优于纯词法。没有通用的中文理解模型，调用方可保留需求并补充忠实英文技术词。拒绝关系不参与查询。未提供审核文件时使用出处校验候选，不能视为语义已审核。

预算包括返回 Markdown 的标题、引用编号和路径行号，超长单元整体略过；审计文件记录选择路径和未装入单元，不发送给回答模型。字符数不是 API Token 数，未返回不表示不存在。

可视化复用已有 graphify 风格的离线浏览器，展示两层图，支持搜索、筛选、邻域、来源及当前 SVG/JSON 导出。Markdown 和数学使用安全 DOM 与本地 KaTeX 显示，保留带行号原文展开视图。条件图保留拒绝候选供审阅，节点状态明确标识；检索会排除这些候选。首次导出需提供本地 KaTeX dist，随后复用已复制的离线资源。

统一评测适配器是项目 `experiments/retrieval_method/evaluate_manual_holdout.py`，题目从外部归档的 `questions.json` 读取，不在代码中保留旧版题集。合并主评测使用 `--variants baseline`；可选提示、预算和主张审核属于单列诊断。同一新版语料、同一字符预算与回答提示，分别记录关键证据覆盖、答案语义、API 累计 Token；构建调用另计。当前合并题集均已用于开发，不能作为独立盲测，也不能用全书结构保真推导图谱降低 Token。
