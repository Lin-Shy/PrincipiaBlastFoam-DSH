# 第2章检索实现与评测


2026-10-16 本轮交付完成：277题/55主题/20关联组，开发77题、测试200题；两模型150配置共13,536会话、全部代理评分、1,248份来源意见及同数引用意见均已完成并独立核验。正式统计含50序列、8项主比较、6项机制比较、42项补充和5项模型规模比较，固定及复核敏感性均保留；8/6项确认性优越结论全部未获支持。400份生成失败、185份固定主指标未知及不利消融方向不删改，本地3,378份部分评分不混入代理成绩。7幅实测图（PDF/SVG/PNG）、9份CSV及9张正文表已交付；109页正式论文和61页可编辑答辩已完成编译/原生导出、视觉审阅及来源清单核验。大批量使用 `.env.qwen_proxy`，小批量使用 `.env.qwen_local`，无隐式供应商回退。最终费用记录93,464次物理尝试、165,003,347已知token和257次缺用量；宿主AI、硬件、电耗及货币成本未完整计量。AI原文复核不是真人真值，冻结题目、Gold、回答与评分保持。 最终范围与交付核验见[完整交付收据](../../../graduation-experiment-results/chapter2_retrieval/knowledge_qa_20261013/audit/complete_delivery_001/verification.json)。

以下过程快照保留各自捕获时的状态；其中“待完成”“运行中”等不代表当前状态。

迁移前历史快照（里程碑146，非当前状态）：当时原84335评分和93790交接仍运行，8B首轮2048非预选绑定及25配置回执已核验；观察133只核验8207份旧评分身份，不是答对数。原进程后续已按本地迁移要求停止，旧分数保持历史身份；当前本地完整范围与状态见本文开头。

首轮完整非预选范围按冻结005计划和预选003身份划分，逐配置核对原worker回执、summary和私有日志字节、非预选分母及退出码。25配置中，主方法/消融各184份，预算配置各36份，完整资料16题全部属于预选所以非预选为0；不能把0误称完整资料诊断已评分或失败。该范围总计2048，并已由独立元数据观察核验评分/回答/协议的绑定和007身份。未读取评分质量标签或日志中的回答，未形成首轮优劣或显著性结论。

本轮只确认新的完整首轮非预选终态覆盖，不中断/重启原评分，不重评或替换模型；当前进程仍继续第二/三轮。后续两模型预选按原3+1顺序和两份新鲜接入证明等待全部6144非预选正常结束。此前四阶段报告入口20项、辅助19项、轨迹20项、最终费用13项及图件交付27项/原8项制图检查保持，最终7图9CSV入口002尚未执行。既有95页论文及115来源清单、56页答辩交付保持；完整13536评分证明、全量统计、实测图件、最终正文与答辩效果交付仍待完成，全部未知和AI/主题记忆/历史标签暴露限制保持，完整目标active。

证据：[里程碑146](../../../graduation-experiment-results/chapter2_retrieval/knowledge_qa_20261013/audit/execution_milestone_146.json)；[8B首轮2048非预选及25原生回执](../../../graduation-experiment-results/chapter2_retrieval/knowledge_qa_20261013/audit/registered8_first_round_nonselected_001.json)；[最终7图9表交付准备](../../../graduation-experiment-results/chapter2_retrieval/knowledge_qa_20261013/audit/final_publication_export_preparation_002.json)；[27项图表交付检查](../../../graduation-experiment-results/chapter2_retrieval/knowledge_qa_20261013/audit/publication_handoff_offline_checks_001.json)；[实际图表入口拒收未完成范围](../../../graduation-experiment-results/chapter2_retrieval/knowledge_qa_20261013/audit/final_publication_real_partial_gate_002.json)；[答辩方法与设计56页交付](../../../graduation-experiment-results/chapter2_retrieval/knowledge_qa_20261013/audit/defense_chapter2_delivery_001.json)；[评分后四阶段入口准备](../../../graduation-experiment-results/chapter2_retrieval/knowledge_qa_20261013/audit/post_score_pipeline_preparation_001.json)；[20项流水线检查](../../../graduation-experiment-results/chapter2_retrieval/knowledge_qa_20261013/audit/post_score_pipeline_offline_checks_001.json)；[实际入口拒收未完成范围](../../../graduation-experiment-results/chapter2_retrieval/knowledge_qa_20261013/audit/post_score_pipeline_real_gate_001.json)；[论文测量边界及32页渲染](../../../graduation-experiment-results/chapter2_retrieval/knowledge_qa_20261013/audit/manuscript_measurement_render_004.json)；[此前139链接更正](../../../graduation-experiment-results/chapter2_retrieval/knowledge_qa_20261013/audit/milestone139_closure_verification.json)；[1248必要原文收据](../../../graduation-experiment-results/chapter2_retrieval/knowledge_qa_20261013/formal_original_review/pack_113/personal-review-receipt.json)；[完整来源释放](../../../graduation-experiment-results/chapter2_retrieval/knowledge_qa_20261013/audit/complete_source_release_verification_001.json)；[原生评分/冻结统计准备](../../../graduation-experiment-results/chapter2_retrieval/knowledge_qa_20261013/audit/full_matrix_analysis_handoff_preparation_001.json)；[辅助维度与失败报告准备](../../../graduation-experiment-results/chapter2_retrieval/knowledge_qa_20261013/audit/auxiliary_report_preparation_001.json)；[19项辅助维度检查](../../../graduation-experiment-results/chapter2_retrieval/knowledge_qa_20261013/audit/auxiliary_dimensions_offline_checks_001.json)；[真实入口拒收未完成评分](../../../graduation-experiment-results/chapter2_retrieval/knowledge_qa_20261013/audit/auxiliary_real_entry_gate_verification_001.json)；[评分观察133](../../../graduation-experiment-results/chapter2_retrieval/knowledge_qa_20261013/audit/formal_grading_live_observation_133.json)；[轮次101](../../../graduation-experiment-results/chapter2_retrieval/knowledge_qa_20261013/audit/formal_round_progress_101.json)；[自动交接监控](../../../graduation-experiment-results/chapter2_retrieval/knowledge_qa_20261013/audit/full_selected_auto_handoff_003/preflight.json)；[全量生成用量](../../../graduation-experiment-results/chapter2_retrieval/knowledge_qa_20261013/audit/two_model_closed_generation_costs_001.json)；[1248轨迹请求诊断准备](../../../graduation-experiment-results/chapter2_retrieval/knowledge_qa_20261013/audit/trajectory_request_report_preparation_001.json)；[20项轨迹证据检查](../../../graduation-experiment-results/chapter2_retrieval/knowledge_qa_20261013/audit/trajectory_request_inclusion_checks_001.json)；[轨迹实际入口拒收](../../../graduation-experiment-results/chapter2_retrieval/knowledge_qa_20261013/audit/trajectory_real_entry_gate_verification_001.json)；[全活动费用准备](../../../graduation-experiment-results/chapter2_retrieval/knowledge_qa_20261013/audit/final_stage_cost_handoff_preparation_001.json)

2026-10-14：新专业问答以[KNOWLEDGE_QA_PLAN.md](KNOWLEDGE_QA_PLAN.md)为工程入口；用户重新激活目标后，新的精确14B检查返回成功响应及已知用量，余额阻塞已由实际证据解除。首次接续因Windows许可收据路径过长退出；本地短路径映射后，原005/007/余额恢复004程序不变，生成24685与非预选评分74366均已由工具确认存活，两条控制器进程链没有重复启动。观察022/019为3432份生成（3415回答、8格式失败、8截断、1HTTP拒绝）及1311份绑定评分，相比停机新增112/57份；原3320生成和1254评分字节保持，失败任务不重发。8B独立检查014仍502/502/503，上游暂不可用，不能以14B替代其自身开发和正式验收。引用包028/主回答包024累计297份意见，新增3份亲自复核，旧294份在完整输入/结果/原文/意见一致后原样延续，007加载器接受；14B首轮208份、第二轮89份。236份有效引用回答/868段候选文字已核对，61份非语义引用状态单列；主完整性和引用支持分别记录。预选评分0，未查看自动语义标签。完整释放执行包003经实际快照核验支持004不可变来源快照，核验引用先行收据及快照/原答案/协议/文件绑定；49项相关测试通过，包括4项全量整合测试，未知意见保持未知。001要求快照路径等于活目录，不能接受实际流程，保留历史身份且从未释放实际评分；002在当前297份部分包上仍拒绝评分。完整150配置/13536会话、1248意见及终止评分分母保持；按捕获尚差951份意见，后续新答案仍需引用先行复核。95页方法/设计/复现稿及115项来源绑定保持，完整两模型效果、统计/实测图件、最终全文与答辩待完成。见[里程碑035](../../../graduation-experiment-results/chapter2_retrieval/knowledge_qa_20261013/audit/execution_milestone_035.json)。

新协议维护入口为[基础agent检索增强实验](AUGMENTATION_PLAN.md)：四组共同保留grep、定位与原文读取，分别新增BM25、E5或图谱，使用用户授权qwen_proxy。归档`grep_augmentation_v4/`的正式8B作答、证据/资源/消融及原评分网格完成，正文和正式图件已同步；原8B评分失败保留未知，后注册14B裁判及同请求网络恢复完成；419全项有效/171部分无效/291输出失败/271空答案。旧`aliyun_8b_cross_source_v1/`保持历史冻结身份，完整回答图谱[14.24,15.28]%/基础1.04%，格式未知保留，主检验不宣布显著优越。

本目录维护算法、评测适配器和审计脚本。实验唯一归档为 `../../../graduation-experiment-results/chapter2_retrieval/`，统一题集为其 `datasets/natural_navigation_qa/`。当前检索增强为`grep_augmentation_v4/`，正式证据/资源结果已同步论文，后注册14B裁判评分及网络恢复完成，修订报告与严格一致性审计独立归档；`aliyun_8b_cross_source_v1/`是历史冻结证据。取材从归档 `论文取材入口.md` 开始。

14B新的精确接入成功，原余额恢复004经本地短路径继续在线生成/非预选评分；观察3432生成/1311评分，297份原文意见完成，预选评分0。完整释放003支持实际来源快照并通过49项测试；8B014仍未恢复。完整实测与最终交付继续待办。完整预选评分入口现为执行包003：直接核验实际004来源快照的297案例/625文件，并按实际evaluation_only/source-snapshot.json与相邻results目录布局重新通过49项测试。001/002的活目录或收据层级假设未覆盖正式流程，保留历史失败身份且未用于实际预选评分。部分快照元数据可以独立核验，但完整控制器/worker在前后均要求全部1248意见，当前评分授权仍false、预选评分0。14B生成24685和非预选评分74366继续在线，8B014接入未恢复；观察3432生成/1311评分、已复核297意见及95页方法稿保持，完整实测/统计/最终稿件待完成。

研究问题、论证主线与方法边界见[第2章共享设计](../../../graduation-thesis-materials/graduation-research/chapters/chapter02.md)。本目录维护具体实现与验证，冻结协议和证据继续由实验归档保存。

## 当前正式实现

- `chapter2_graph_retriever.py`：免外部索引图检索与结构化原文回读。
- `chapter2_canonical_delivery.py`：权威证据映射、去重、原生排名与实际字符预算。
- `chapter2_role_graph.py`：角色增强和跨来源关系。
- `chapter2_common_planner.py`、`chapter2_cited_answer.py`：轻量模型公共规划和带引用回答。
- `chapter2_formal_*`：正式输入、实现冻结、执行和评分；现有冻结运行自带 runtime 快照。

离线构图/语义校验使用 `deepseek-flash`，在线过程按轻量模型协议，最新为 `qwen3-8b`。留出集不锁定，gold 仅由评测侧读取。自研链路只持久化图与构图清单；E5/BM25是隔离对照，不进入自研最终方法。

历史 `candidate_qa.py` 的二阶段默认替换、旧轮次和 post-hoc 指标只解释当时开发实验，不作为当前正式结果入口或新实验停止条件。历史冻结源码/回答/评分不改；当前源文件的更改不等于重新生成冻结结果。

论文仅在 `../../../graduation-thesis-materials/graduation-manuscript/` 以 LaTeX 维护；最终图件与 CSV 位于该项目 `assets/chapter2/`。制图脚本在 `../../../graduation-thesis-materials/graduation-visualization/`。

## 历史本地人工评分（新协议不使用）

`chapter2_human_rating.py` 生成48份冻结回答的离线HTML，支持事实/引用两项五分制、选填备注、缓存续审、JSON/CSV导出及封存后解盲。用法与新增量表协议见 [human_rating_README.md](human_rating_README.md)。原二元盲审脚本和冻结评分保持原样；此入口不调用模型，不自动生成真人判断。

迁移前释放实现修正记录（非当前状态）：当时完整预选评分入口为执行包003，直接核验实际004来源快照的297案例/625文件，并按实际evaluation_only/source-snapshot.json与相邻results目录布局通过49项测试。001/002的活目录或收据层级假设未覆盖正式流程，保留历史失败身份且未用于实际预选评分。当时全部1248意见尚未齐备，评分未获释放；该数量与进程状态只解释历史快照，当前状态以本文开头的本地迁移进度为准。证据见[实际快照核验](../../../graduation-experiment-results/chapter2_retrieval/knowledge_qa_20261013/audit/full_review_snapshot_002/README.md)。

## 本地评分后的交接入口

当前活动为 `../../../graduation-experiment-results/chapter2_retrieval/knowledge_qa_20261013/`。所有入口均显式传入 `--activity` 和 `--activation <活动>/setup/local_uniform_judge_004/activation-002.json`；历史代理回执不作为本地完成证明。

| 顺序 | 维护入口 | 执行条件与交付 |
| --- | --- | --- |
| 1 | `chapter2_verify_local_score_terminal.py` | 根会话实际观察评分进程退出后保存原生回执，以 `--native-observation` 传入；独立核验13536评分和1248来源意见，输出 `<活动>/audit/local_qwen_transition_001/local_score_native_terminal_004.json`。进程仍运行时不能创建正常退出回执。 |
| 2 | `chapter2_run_local_analysis.py --execute` | 消费完整本地证明；保留原007统计、50系列及8/6/42/5比较范围，输出 `formal_analysis/two_model_local_004/`。 |
| 3 | `chapter2_build_local_post_reports.py --kind auxiliary --execute` | 完整分析后，按冻结规则汇总辅助维度和重叠失败标签，输出 `formal_analysis/auxiliary_dimensions_local_004/`；未知维度不计零，条件分母仅含相应题目。 |
| 4 | `chapter2_build_local_post_reports.py --kind trajectory --execute` | 保留全部1248预选案例，区分工具交付与记录请求中的原文，输出 `formal_analysis/prospective_request_inclusion_local_004/`；不声称供应方实际处理或模型语义阅读。 |
| 5 | `chapter2_collect_local_final_costs.py --execute` | 完整评分结束后核对原生成基线及本地裁判账本，分别列旧代理和本地阶段，输出 `audit/stage_costs_local_final_004/`；保留失败、未知用量和未决历史尝试。 |
| 6 | `chapter2_export_local_publication.py --execute` | 前述分析和报告全部绑定后，复用原绘图脚本导出7图（PDF/SVG/PNG）及9张CSV到论文 `assets/chapter2/knowledge_qa_results/`；随后仍须亲自审图、核对结论、修改和编译论文及答辩。 |

各准备记录已保存于活动 `setup/local_uniform_judge_004/`。输出目录存在时入口拒绝覆盖；部分费用观察不能替代最终结账，入口检查通过不代表实验效果或最终交付已完成。
