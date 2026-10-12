# CLI 查询、旧入口与维护

从 blastfoam-knowledge 技能目录运行下列命令。此参考用于 MCP 不可用、批量查询或图谱维护；日常已知案例定位先按 SKILL.md 选择入口。

## 查询

需求涉及未知案例、未知配置位置或多份关联资料时，优先用定位入口收窄范围，再按返回路径与行号读原文；已有准确来源位置时直接读取。

```bash
python scripts/locate.py --query "<用户原始需求>" --translation "<可选的忠实英文表达>" --domain-index <外部已审核领域图.json> --budget 3000
```

无需事先查出节点 ID。`locations` 给出候选位置、原文前缀和定位理由，`preview_complete` 标明是否完整；`relations` 给出关联位置和导航方向，`facts` 给出审核条件及逐字引句。已返回引句无需再读。反向导航不反转逻辑含义。未传领域图只启用结构回退，`semantic_facts_available` 为0。不要把 `query_match` 当作适用性结论。中文表达可由调用智能体补充英文翻译，不猜测未知模型名。没有合适候选时针对缺失概念改写查询或退回文本搜索，不重复调用同一定位请求。细节与消融见[定位入口说明](locator.md)。

新版手册已经提供章节 Markdown。重建手册图、查询章节原文或检查已审核的条件关系时，使用[章节与原文证据图](manual-graph.md)中的 `manual_graph.py`、`manual_semantic.py`、`manual_search.py` 和 `export_manual_graph.py`。构建与评测产物保存在调用方指定的外部归档目录；语义查询需显式传入对应的基础图、语义图和审核记录。原始 Markdown 保留公式、表格及插图，出处校验与语义审核分别记录。

需要按用户需求一次获取多份相关配置原文时，可使用新增的紧凑证据包入口（开发验证阶段）：

```bash
python scripts/evidence_bundle.py search --query "记录固定位置压力并控制全场输出频率；pressure probes time history field output interval" --budget 6000
```

保留原始需求，可补充忠实的英文技术表达；不添加用户未给定的案例名、参数值或物理假设。此步骤由调用 skill 的智能体完成，脚本自身不调用模型。中文词表不是任意自然语言理解器；零命中或候选偏离时应改写技术表达，不能认为没有相关资料。

该入口先定位最多两个候选案例，再按配置作用域、脚本输入线索和手册定义组织原文。`sources` 将短 ID 映射到路径和 SHA-256；`evidence` 给出完整行的原文、行号和作用域，已读取的证据不用再逐条调用 `source`。预算包括返回 JSON 的元数据，重叠行和完全相同片段不重复返回。候选仍需判断物理适用性，证据包不是完整修改方案。

组织回答时按来源路径区分候选案例，不把不同案例的网格、参数或边界拼成同一案例配置。先检查必要依据是否已在包中，再陈述缺口；资料已返回而答案未使用，应改进答案，不重复检索同一片段。只有运行、配置与物理条件的证据足够时才给出具体修改建议。

有明确案例时增加 `--case tutorials/<求解器>/<案例>`。需要补查时围绕仍缺失的依据改写查询，或按返回路径读取相邻原文；不要把同一完整证据包和历史工具结果反复追加到上下文。保留后续回答需要的原文与引用即可。公式或复杂表格请读取对应 Markdown 原文及其引用插图。

首次使用可在内存构建派生配置图，不改动已有索引。批量查询可用 `build --index <外部归档目录>/derived-graph.json` 保存，再向 `search` 传同一 `--index`。新增构建、预算与关系边界见[紧凑证据包说明](evidence-bundle.md)。`--strategy text|files|graph` 为同一入口的对照策略，默认 `graph`；默认值不代表已证明图谱优于另外两组。

需要直观检查图谱时，运行 `python scripts/export_visualization.py --output <外部归档目录>/graph`，可选 `--index <冻结配置索引>`。导出离线 HTML、完整 JSON 和 SVG 总览，支持切换原有语义定位图与配置证据图、筛选案例和查看原文；详见[可视化导出说明](visualization.md)。

以下旧导航入口依赖尚未随新版语料重建的全局语义图，当前默认安装不可用；仅在显式恢复并验证该图后使用。正常定位使用上面的 `locate.py`：

不确定图谱中的准确名称时，先发现真实实体，再查看卡片与原文：

```bash
python scripts/navigate.py discover --query "velocity" --scope manual --budget 3000
python scripts/navigate.py inspect --entity <返回的ID> --scope manual --budget 3000
python scripts/navigate.py neighbors --entity <返回的ID> --scope manual --budget 3000
python scripts/navigate.py source --path <返回的来源路径> --start <行号> --budget 3000
```

`discover` 搜索实际名称和命名空间；中文需求可先转成英文概念，再从返回目录中选 ID，不凭记忆编造名称。没有合适候选时用较宽的词、空查询分页浏览，或补查下面的文本入口。`inspect` 展示实际关系种类及其全部候选卡片，不要求预先猜测关系类别。`neighbors` 仅表示实体在同一卡片中出现，不是已验证的因果或修改依赖。来源摘要仍须通过原文核查。

指定案例时，各步都传入同一完整路径 `--case tutorials/blastFoam/building3D`；指定 `--scope manual` 可只查手册。`next_offset` 用于目录续页，`next_line` 用于原文续页；每次字符预算包含元数据，智能体还应累计多次调用的总开销。完整规则与边界见 [图谱导航说明](navigation.md)。

需要按实体和关系定位原文、控制送入智能体的上下文长度时，使用全局图谱入口：

```bash
python scripts/query_global.py --terms activationModel pressureBased --budget 8000
```

由使用 skill 的智能体将问题转换为有依据的英文实体名；必要时添加 `--relation` 或完整语料案例路径 `--case tutorials/blastFoam/building3D`。不确定关系时先不筛选。此入口不使用 BM25，预算按返回 JSON 的 Unicode 字符数计算，包含元数据。来源卡片保留适用条件与原文定位，但尚未独立完成语义复核；不能据此推断完整修改依赖。构建、增量更新与覆盖边界见 [全局图谱说明](global-graph.md)。未命中时可使用下面的文本与结构图入口补查。

选择教程：

```bash
python scripts/query.py --mode cases --query "建筑物 STL 爆炸绕射，需要压力时程" --limit 5
```

定位指定案例的配置，并关联手册定义：

```bash
python scripts/query.py --mode search --case blastFoam/building3D --query "activationModel 起爆模型与 README 是否一致" --limit 6
```

查询手册：

```bash
python scripts/query.py --mode manual --query "linear pressureBased 起爆模型区别" --limit 6
```

`--mode search` 不指定案例时搜索全部资料；`--mode auto` 只做简单意图分流，复杂需求请显式选择模式。将复合问题拆成案例选择、配置定位、模型定义等子查询。中文召回不足时，用返回的英文术语或字典键补查。

普通搜索与手册查询的 `results` 是统一排序后的完整证据列表，总数不超过 `--limit`；`related_evidence` 是其中带图谱路径的子集，不要再次拼接。`graph_path` 给出起点证据、连接方向和最多三条关系，`ranking` 区分词项得分与图谱支持。案例选择模式仍返回候选案例及其证据，附加证据单独展示。

不要求教程示例时，手册查询不反向扩展到任意案例；明确指定 `--case` 时，扩展同样遵守案例范围。`graph_relations` 仅包含入选证据的连接依据。`issues` 给出所涉案例的文档/配置冲突。案例分数衡量文本相关性，仍须根据任务的物理过程、求解器、几何假设和目标输出判断适用性。必要条件未知时指出缺口，不按排名直接宣布唯一适用案例。

## 阅读证据并组织回答

```bash
python scripts/source.py --path tutorials/blastFoam/building3D/constant/phaseProperties --start 80 --end 122
```

返回证据含语料相对路径、SHA-256、行号；配置还含 `dictionary_path`。手册证据使用原始 Markdown 路径与行号。按需打开 `corpus/` 下原文；公式和表格直接读取 Markdown，插图位于同目录的 figures/。

回答应给出：候选与匹配理由，相关文件/字典路径或手册 Markdown 行号，必要的关联步骤，以及证据中明确的冲突与缺口。引用实际来源。不要把教程取值推广为通用推荐参数，或把脚本中的命令视作已成功执行。

`NEXT_IN_SCRIPT` 仅代表静态出现顺序；条件、循环、环境变量与运行时产物未经执行验证。`REFERS_TO_DEFINITION` 是名称及上下文匹配，需检查返回的手册上下文。未解析的 include/表达式保存在图谱诊断中，不会执行 `#codeStream` 或补猜数值。

README 与配置不同时，保留两个来源，当前配置以实际字典说明。没有命中不等于语料中不存在；明确案例路径不存在时入口返回 `case_unavailable`，但自然语言的“无匹配”仍需查清单或补查术语。

## 更新与维护

用户提供的高保真手册已完整复制到 `corpus/manual/markdown/`（包含 `figures/`）。后续结构索引和全局图谱构建直接使用此目录的 Markdown；不再经过 PDF/OCR 转写。旧分页文本、抽取方法、视觉/语义试抽结果及旧索引已清除。全局图谱必须重新生成后才能使用 `query_global.py`、`navigate.py` 等依赖它的入口。


将教程增删改同步到本 skill 的 `corpus/tutorials/` 后，运行 `python scripts/build.py`，再运行 `python scripts/validate.py`。外部原教程目录的变化不会自动修改此固定副本；同步时应同时处理删除项，而不只是覆盖新增文件。查询检测到语料变化会要求重建，避免使用已删除或过期的来源。首次使用已附带的语料和索引无需重建。

修改抽取逻辑、维护教程别名或检查构建限制时，阅读 [构建与图谱说明](architecture.md)。不要把 `dataset/` 中的问题、标注和实验结果加入语料或术语表。

全局抽取产物属于候选来源定位图。后续进行独立语义复核与修改依赖推理时，阅读 [语义事实与依赖扩展约定](semantic-contract.md)；完整修改推理尚未通过验收。
