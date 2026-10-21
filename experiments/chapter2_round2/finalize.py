"""阶段交付说明；汇总真实回执，不修改已有文件。"""
from common import *

def main():
    s=read(ARCHIVE/'evaluation/final_001/summary.json')
    methods=sorted(s['methods'])
    if len(methods)!=11 or any(v!='complete' for v in s['methods'].values()):raise ValueError('all11 methods required')
    preservation=read(ARCHIVE/'audit/historical_preservation.json')
    if not preservation['preserved']:raise ValueError('historical preservation failed')
    stages=dict(audit='complete',new_text_baselines='complete',new_graph_ablations='complete',fixed_query_retrieval='complete',
        formal_14b_generation='pending_user_approval',paid_judging='pending_separate_protocol_and_user_approval',
        historical_failure_cases='complete_explanatory_only',human_review_export='complete_labels_pending',
        graph_quality_export='complete_labels_pending',new_holdout='not_started_template_only',
        thesis_outputs='draft_tables_figures_notes_complete_original_manuscript_unchanged')
    commands=[
        ('audit', 'python -X utf8 PrincipiaBlastFoam-DSH/experiments/chapter2_round2/audit.py prepare'),
        ('tests19', '& PrincipiaBlastFoam-DSH/.local/knowledge-qa-venv/Scripts/python.exe -X utf8 -m pytest PrincipiaBlastFoam-DSH/experiments/chapter2_round2/test_round2.py PrincipiaBlastFoam-DSH/experiments/chapter2_round2/test_workflows.py -o addopts= -q'),
        ('bge_download','python -X utf8 PrincipiaBlastFoam-DSH/experiments/chapter2_round2/download_bge.py'),
        ('bge_index','& PrincipiaBlastFoam-DSH/.local/knowledge-qa-venv/Scripts/python.exe -X utf8 PrincipiaBlastFoam-DSH/experiments/chapter2_round2/bge_m3_dense.py'),
        ('retrieval_freeze','python -X utf8 PrincipiaBlastFoam-DSH/experiments/chapter2_round2/retrieval.py freeze'),
        ('bge_index_seal','python -X utf8 PrincipiaBlastFoam-DSH/experiments/chapter2_round2/bge_runs.py seal')]
    for m in methods:
        script='bge_runs.py' if m in ['bge_m3','bm25_bge_m3'] else 'retrieval.py'
        commands.append((m,f'& PrincipiaBlastFoam-DSH/.local/knowledge-qa-venv/Scripts/python.exe -X utf8 PrincipiaBlastFoam-DSH/experiments/chapter2_round2/{script} run --method {m} --run-id fixed200_v1'))
    for script,args in [('evaluate.py','--run-id fixed200_v1 --output final_001'),('validate_traces.py','--run-id fixed200_v1 --output graph_trace_invariants.json'),
        ('validate_bge.py','--run-id fixed200_v1'),('analyze_results.py','--evaluation final_001 --output analysis_final_001'),
        ('cases.py','--evaluation final_001 --output cases_final_001'),('plot_results.py','--source final_001 --output final_001'),
        ('plot_reviewed.py',''),('source_figures.py','--run-id fixed200_v1 --output source_trace_002'),
        ('human_review.py','export'),('holdout_gate.py','template'),('costs.py',''),('e2e.py','prepare'),
        ('audit.py','verify --output historical_preservation.json')]:
        commands.append((script,'python -X utf8 PrincipiaBlastFoam-DSH/experiments/chapter2_round2/'+script+' '+args))
    status=dict(schema='round2_offline_delivery_v1',stages=stages,methods=methods,questions=200,budgets=[2000,4000,6000],
        delivered_packets=6600,original_historical_files_preserved=preservation['files_checked'],new_paid_llm_requests=0,
        new_holdout_questions=0,new_holdout_queries=0,human_labels='pending',
        retrieval_protocol_sha256=sha(ARCHIVE/'configs/retrieval_v1.json'),bge_index_seal_sha256=sha(ARCHIVE/'configs/bge_query_binding_v1.json'),
        e2e_protocol_sha256=sha(ARCHIVE/'configs/e2e_14b_v1.json'),e2e_status='frozen_pending_user_approval',
        source_files={p.name:sha(p) for p in HERE.glob('*.py')},commands=[dict(stage=k,command=v) for k,v in commands],
        actual_results=s['overall'])
    save(ARCHIVE/'delivery_status.json',status)
    text=['# 第二轮阶段交付（2026-10-20）','','## 已完成','',
        '- 审计两份文件已交付；37实现及原图/语料/题目/评分哈希一致。结束时再次逐文件核验33,362个历史文件，改动、缺失、新增均0。',
        '- B1/B2/B3与A1/A2、统一固定预算检索已实现；11方法×200题×3预算=6600交付全部完成。',
        '- 主测试19通过；后续评价/授权/真实BGE索引测试7通过（其中6项为前一轮测试的相关复验，独立用例共20项）。XML：audit/tests_002.xml、tests_003.xml。',
        '- 200题A1/A2轨迹不变量全部通过；200题独立BGE运行与混合右路排序逐项完全一致。文本组实际打开文件无Gold/图，BGE未加载Sparse/ColBERT权重。',
        '- BGE官方版本5617a9f61b028005a4858fdac845db406aefb181，861片段、1024维、CPU float32，索引构建1011.94秒、截断0。',
        '- 40题四类各10，图/BM25共80匿名回答、160评审记录；图50节点/50关系/30别名空表已导出。标签全pending。',
        '- 实测表CSV/JSON、预算曲线、四类型图、真实局部图、真实来源追踪、成功/失败案例和2.2–2.6改稿草案已生成。','',
        '## 各阶段修改、命令与结果','',
        '|阶段|实际新增源码|实际产物与问题|','|---|---|---|',
        '|0|common.py、audit.py|audit/current_state.md、implementation_matrix.md、checks.json；Git既有修改保留，单次safe.directory只读审计|',
        '|1|text_baselines.py、download_bge.py、bge_m3_dense.py、bge_runs.py|indexes/；BM25与E5历史分段并不相同；本轮BM25/BGE完全同分段|',
        '|2|graph_ablations.py、validate_traces.py|audit/graph_trace_invariants.json；旧with_paths同时关闭上下文且漏关文档引用查找，已在新增适配器分离|',
        '|3|retrieval.py、evaluate.py、validate_bge.py、plot_results.py、plot_reviewed.py、analyze_results.py|runs/fixed200_v1、evaluation/final_001、figures/reviewed_001；所有预算合法、重复行率0|',
        '|4准备|e2e.py、costs.py|configs/e2e_14b_v1.json已冻结待审批；私有代理单价/余额/RPM/TPM未知；需400核心参照重跑|',
        '|5|cases.py、source_figures.py|reports/cases_final_001、figures/source_trace_002；历史QA与本轮检索严格分批标识|',
        '|6|human_review.py、graph_review_summary.py|human_review/及pending汇总；不能计算独立人工准确率|',
        '|7准备|holdout_gate.py|holdout/holdout_freeze_manifest.template.json；not_frozen，未创建或测评新题|',
        '|论文草稿|analyze_results.py|reports/analysis_final_001/；未改历史正文、评分或正式图|','',
        '以下均为本轮实际执行命令或逐方法命令的等价展开，复现须使用新的输出ID，禁止覆盖或重发同号运行。','', '```powershell']
    text += [v for k,v in commands]
    text += ['```','','## 正在执行','', '无需付费阶段已完成，等待付费审批与真实人工标签。','',
        '## 未开始或阻断','',
        '- 新14B正式生成和付费裁判均未发起。新代码使用历史Agent、提示、预算及部署路由；新公共行去重改变消费者协议，故原完整图/BM25不能充当同批确认性参照。',
        '- 留出60题未开始；必须先结束开发集方法决策与正式协议/评分冻结，再做人审、事实隔离审计和单独授权。',
        '- 人工标签未返回；图正确率、双人一致性和人审Gold准确率均不能填数。','',
        '## 需用户决策：正式付费批次','',
        '建议7组×200=1400会话：新增B1/B2/B3/A1/A2共1000，加完整图/BM25核心参照400。14B代理、非思考、温度0、相同原预算、单次失败不重试；各方法顺序执行，不叠加并发。',
        '按历史图/BM25共400会话的真实回执估算：生成约3346请求、6.858M输入/0.347M输出token；另行评分约5145请求、7.966M输入/0.989M输出token，历史有1条裁判用量未知，不能按0计。',
        '生成的协议预算上限为275.251M输入/22.938M输出token；经验均值不是费用上限。裁判/生成审批分别记录；未知失败用量保留。',
        '实际代理单价、余额、RPM/TPM均未获得；仓库16并发上限不能当作供应商额度。若输入/输出每百万token单价分别为P_in/P_out，经验总费用约14.824×P_in + 1.335×P_out，另保留未知消耗。未冒用其他供应商公开价。',
        'e2e_14b_v1协议SHA256：`'+status['e2e_protocol_sha256']+'`。等待用户提供实际价格/额度并确认范围后才启动；没有批准文件，执行门拒绝运行。','',
        '## 结论边界与复现说明','',
        '当前结果仅为暴露200题、固定自然问题的登记证据检索。BGE Dense未超过BM25；融合提升有限且多资料类型可能下降。关闭关系遍历的整体差异较小；仅锚点下降还反映节点锚点与登记证据粒度差异，不能直接证明父内容单独有效。',
        '本轮分组bootstrap分析在初步结果之后追加，明确为探索性；不宣称确认性显著或未见泛化。原文送达、语义支持、回答正确、物理有效性分别解释。',
        'evaluation/interim_001为早期过程快照，其评价脚本在运行期间加入了离线缓存优化，运行时源码哈希不具备精确版本证明；不作为交付证据。最终仅引用final_001与其冻结输入哈希，所有中间产物保留。',
        '最终科学图表当前是独立可追溯草稿；获准正式实验后再做稿件补丁。源文件原工作树未提交，所有新源码按实际SHA256封存，Git HEAD不能替代工作树绑定。']
    (ARCHIVE/'STAGES.md').write_text('\n'.join(text)+'\n',encoding='utf-8')
    (ARCHIVE/'README.md').write_text('# 第2章第二轮：无需付费阶段已完成\n\n11方法×200题×3预算=6600实际交付；付费LLM请求0，新留出验证0，历史33362文件逐个哈希未变。\n\n- [阶段修改、命令、测试、问题与审批](STAGES.md)\n- [审计](audit/current_state.md)、[实现矩阵](audit/implementation_matrix.md)\n- [正式固定查询结果](evaluation/final_001/retrieval_report.md)、[机器结果](evaluation/final_001/summary.json)\n- [正文草稿与分析](reports/analysis_final_001/thesis_revision_notes.md)、[案例](reports/cases_final_001/cases.md)\n- [分组预算图](figures/reviewed_001/text_baselines.png)、[消融图](figures/reviewed_001/graph_ablations.png)、[四类型](figures/reviewed_001/four_types.png)\n- [人工核验材料](human_review/README.md)\n- [待批准14B冻结协议](configs/e2e_14b_v1.json)、[成本依据](reports/cost_estimate.json)\n\n固定查询检索不是端到端QA；没有新EAS、人审准确率或留出结果。\n',encoding='utf-8')
    print('offline delivery complete; paid generation/judging and holdout remain pending explicit approval')

if __name__=='__main__':main()
