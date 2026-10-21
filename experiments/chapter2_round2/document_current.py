"""Reconcile live documentation; leave frozen protocols and dated reports intact."""
import re
from datetime import datetime,timezone
from common import *

MATERIALS=WORKSPACE/'graduation-thesis-materials'
changes=[]


def write(path,text):
    before=sha(path)if path.exists()else None
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(text.rstrip()+'\n',encoding='utf-8')
    changes.append(dict(path=path.relative_to(WORKSPACE).as_posix(),before_sha256=before,after_sha256=sha(path)))


STATE='''## 第2章当前状态（2026-10-20统一维护）

- 原200题、69主题、24知识组及评分标注保持不变，全部问题已人工审核。活动题集实体为`graduation-datasets/chapter02_knowledge_qa/development_v1_160/`与`test_v1_40/`，各自维护model/与scoring/；formal_v2_200仅作原件。
- 原160题用于开发调参，原补充40题为从未参与调参的未见留出集；依据研究者对未同步记录的更正确认，沿用已有ID与调参设置，不补造冻结时间，不重新选题。测试14主题、5知识组、四类7/6/20/7，开发四类43/44/30/43；不宣称测试均衡或未见文档。
- 当前结果统一由`graduation-experiment-results/chapter2_retrieval/current/results.json`管理；实体在`current/qwen3-8b/`和`current/qwen3-14b/`各自的development/与test/下，按方法/original或replicate/题目ID存放生成与评分。旧独立分集目录仅保留历史统计与迁移说明。
- 主比较统一九种方法：完整图、BM25、E5 Dense、BGE-M3 Dense、BM25+E5、BM25+BGE-M3、BM25父上下文、基础搜索、模型直接作答。消融四项：去来源关联、去中文别名、关闭关系遍历、仅锚点。E5和BGE同时保留；新Embedding仅BGE-M3 Dense。
- 全部既有生成和评分已闭合：8B原1600、14B原1600、14B新增与复验1400，合计4600会话（开发3680、测试920）。8B只运行原六方法/两消融，不伪造其新增方法结果。32B无结果，等待API及另行协议和预算。
- 用户已确认统一总表保留完整图/BM25原运行和复验两行，不平均或择优。公共逐行去重消费者存在差异；统计保留原5主比较/2消融与复验4主比较/2消融的校正族，不做跨协议确认性拼接。40题5知识组比较均未达保守校正显著性，不能沿用全200题24组结论。
- 题目审核与独立评价核验分开。用户已确认AI裁判人评和来源图质量抽查尚未完成，保持pending；80份匿名回答需两位评审各80条标签，图抽查50节点/50关系/30别名。不能用合成控制代替人评准确率。
- Gold、必要点、权重、证据和人评表仅限评分侧；不进入构图、索引、检索、回答或学习输入。原始题目、图、语料、生成、评分及冻结协议不改，失败0分、未知保留边界。拒绝的新40/60题草稿已清理，不再新建题目。
'''

BOUNDARY='''## 第2章正式方法与维护边界

完整图已被接受，不再依据测试成绩择图；自然语言条件保留，不使用结构化条件字段。自研检索只依赖持久图和原文，不加载外部BM25、E5、BGE、倒排或向量索引。三个新增文本基线不访问图。

主指标为端到端有效回答得分，严格完整有效率为辅助；开发160与测试40分别保留完整分母。基础搜索只有glob/grep/原文读取，直接作答无工具，其他组有各自专用后端；不能写成工具集合完全相同的纯后端比较。

原批次、基线复用、基础搜索后补、图选择与指标修订历史和AI裁判偏差须披露。统一管理不改写冻结快照或历史校正族。当前索引及待办以current/README.md、results.json和TASKS.md为准；答辩尚待同步，32B无结果。
'''


def main():
    for rel in ['AGENTS.md','graduation-datasets/AGENTS.md',
                'graduation-thesis-materials/graduation-manuscript/AGENTS.md',
                'graduation-experiment-results/chapter2_retrieval/AGENTS.md']:
        path=WORKSPACE/rel;text=path.read_text(encoding='utf-8')
        # Superseded prefatory duplicates are removed; live policy is explicit.
        text=re.sub(r'^> 当前实体分集.*\n\n','',text,flags=re.M)
        text=re.sub(r'^> 2026-10-20最新指令.*\n\n','',text,flags=re.M)
        text=re.sub(r'## 第2章当前数据范围[^\n]*\n.*?(?=\n## |\Z)',STATE+'\n',text,flags=re.S)
        text=re.sub(r'## 第2章正式方法与维护边界\n.*\Z',BOUNDARY,text,flags=re.S)
        text=text.replace('留出集不锁定，但 gold 仅限评分侧，不能进入被测输入或构图。','当前40题测试身份固定，不根据测试结果继续调参；gold仅限评分侧。')
        text=text.replace('第2章仅报告当前200题正式实测；','第2章报告当前160/40分集实测；')
        text=text.replace('第2章题集入口为`../../graduation-datasets/chapter02_knowledge_qa/formal_v2_200/`，所有方法使用同一题集。留出集不锁定，gold 不进入被测模型。',
            '第2章活动题集为`development_v1_160/`与`test_v1_40/`，同一子集各方法使用相同ID；gold不进入被测模型。')
        write(path,text)
    path=PROJECT/'AGENTS.md';text=path.read_text(encoding='utf-8')
    text=re.sub(r'- 第2章离线构图使用精确.*?\n','- 第2章模型与部署以各冻结协议为准。合成行为控制已通过，独立人工校准仍pending；生成与评分已闭合4600会话，32B无结果。\n',text)
    text=text.replace('留出集不锁定，可按新协议评测；','当前40题测试身份固定，不按其结果调参；')
    text=text.replace('检索-only主指标使用 Recall@1/3/5/10、Complete Evidence Set Success@5/10、MRR、nDCG@10，并同时给出 6000/12000/24000 返回字符预算下的证据召回；',
        '历史检索计划与正式固定查询分开：当前固定查询按2000/4000/6000实际序列化字符、11种检索配置执行，汇总见current/retrieval-summary.json；只报告实际计算且定义清楚的指标，未实现的nDCG不得虚报。')
    a=text.index('本仓库是当前应用唯一开发入口，第3章与第4章基于DSH。')
    b=text.index('\n实施见',a)
    text=text[:a]+'本仓库是当前应用唯一开发入口，第3章与第4章基于DSH。\n\n'+STATE+text[b:]
    write(path,text)
    current_readme='''# 第2章实验统一入口

更新时间：2026-10-20。当前采用原200题的开发160/未见留出测试40划分，原始回答与评分不变；九种主方法、四项消融统一呈现，E5与BGE-M3同时保留。

## 题集与实体问答

- [开发160题](../../../graduation-datasets/chapter02_knowledge_qa/development_v1_160/README.md) · [测试40题](../../../graduation-datasets/chapter02_knowledge_qa/test_v1_40/README.md) · [ID与研究者更正确认](../../../graduation-datasets/chapter02_knowledge_qa/split_dev160_test40_20261020.json)
- [统一机器索引](results.json) · [逐文件来源及哈希](physical-records.json)

|回答模型|开发160题|测试40题|全部既有会话|
|---|---|---|---:|
|Qwen3-8B|[1280会话](qwen3-8b/development/README.md)|[320会话](qwen3-8b/test/README.md)|1600|
|Qwen3-14B|[2400会话](qwen3-14b/development/README.md)|[600会话](qwen3-14b/test/README.md)|3000|
|合计|3680|920|4600|

各实体目录都包含generation/、scoring/、scoring_payloads/、provenance/及统一统计。记录按方法/original或replicate/题目ID分开；session-metrics.json中的record保持原评分对象，外围字段仅定位来源。旧单独分集目录只保留历史统计和迁移说明，不再存活动问答实体。

## 统一比较与真实运行范围

九种方法：完整图、BM25、E5 Dense、BGE-M3 Dense、BM25+E5、BM25+BGE-M3、BM25父上下文、基础搜索、模型直接作答。四项消融：去来源关联、去中文别名、关闭关系遍历、仅锚点。8B只完成原六方法和两消融，其余不填推测值；14B拥有全部方法及两次核心参照。

用户已确认主表保留完整图/BM25原运行及复验两行。复验使用公共逐行去重消费者，不能平均或择优后隐去差异；也不追加跨协议确认性比较。原5项主比较/2项消融与复验4项主比较/2项消融分别保留Holm族。

40题完整图EAS：8B原32.3–38.1；14B原62.0、复验57.4–60.5。14B的E5为36.6、BGE为51.1，包含分段及运行差异。测试只有5知识组、四类7/6/20/7；全部保守校正检验未确认优势，不沿用原24组显著性。未见调参问题不等于未见文档，划分补录不回写执行日期。

## 固定查询与评价可信度

- [固定查询分集汇总](retrieval-summary.json)：原11配置×200题×3预算的6600份交付，开发5280、测试1320；2000/4000/6000实际JSON字符。它不是自主Agent的过程召回。
- [人工核验入口](HUMAN_REVIEW.md)：用户已确认未完成，80份回答/两评审160条标签、50节点/50关系/30别名均pending；不虚报裁判或图准确率。
- [任务状态与后续顺序](TASKS.md) · [冲突与文档审查](DOCUMENTATION_AUDIT.md) · [本次变更与运行命令](unified-maintenance.md)

## 冻结来源档案

以下保留执行时真实身份和协议，不作为另一套当前结论：原[8B修订](revision_200_20261019_002/README.md)、[14B原七组](model14b_200_20261019_002/README.md)、[基础搜索](basic_search_200_20261019_001/README.md)、[新增及复验原回执](../round2_20261020/e2e_runs/answer14b_003/README.md)。此前独立归档只保留不可改写的原回执、协议、索引和 dated 审计；活动结果全部由本入口管理。拒绝的新40/60题已清理，不再构造或运行。

论文表图使用build_unified_results.py及assets/chapter2/dev160_test40/source-manifest.json。当前更新包括统一方法、固定查询与160/40分母；PDF及发布清单以稿件正式交付为准，答辩PPT尚待同步。32B尚无结果，不自动启动新付费任务。
'''
    write(CURRENT/'README.md',current_readme)
    tasks='''# 第2章主任务状态与下一步

更新时间：2026-10-20；本文件是当前待办入口。原任务书中的额外60/40题、420/280会话计划已被用户撤销，改为原题160+40，不恢复。

|阶段|实际状态|证据/下一步|
|---|---|---|
|仓库/协议审计、隔离与BGE Dense实现|完成|原审计、索引绑定和冻结源码保留；不增加其他Embedding或GraphRAG|
|三档固定查询、11配置|完成并入文|6600原交付按开发5280/测试1320归集，retrieval-summary.json；召回与最终回答分开|
|14B新增/复验生成及付费评分|完成|1400会话闭合，连同原3200会话统一管理为4600；未知、失败与原分数保留|
|九方法/四消融统一表图与统计|本次完成|E5与BGE并列，完整图/BM25两次参照分列，原校正族不改|
|实体开发/测试题集和问答|完成并统一入口|两个题集目录，两个回答模型各自development/test；42243文件与来源一致|
|独立AI裁判人工校准|等待真人，用户确认尚未完成|80份回答、两位评审各80条标签；回填后算一致率、kappa、AI/人工差值与敏感性，不改历史分数|
|图结构质量抽查|等待真人，用户确认尚未完成|50节点、50关系、30中文别名；报告真实分母及错误类型|
|失败与反常机制案例|已有原200题案例，仍需完成测试40题正文案例链|至少成功补证、条件错误、BM25胜出、混合排序和预算可能性；有原轨迹才下机制结论|
|真实局部图与一道题来源追踪图|尚待落实到当前稿件|必须来自冻结图和真实轨迹，不以示意流程图代替实际结构证据|
|方法论证与正文精简|尚待一轮结构修订|压缩直观预算/遍历性质，将详细证明与资源日志移附录；保留条件性边界|
|答辩PPT/PDF|待同步|九方法、四消融、160+40、5组不显著及pending人评必须一致|
|32B或8B新增基线复验|可选，未启动|32B无API；只有明确研究需要并冻结方法范围、规模/成本后执行，不把它当已完成结果|

## 接下来按此顺序

1. 自动可继续：补齐测试40题成功/失败案例、真实图局部与原文追踪，并完成机制章节结构修订；全部使用既有数据，不调用付费模型。
2. 人工并行：按HUMAN_REVIEW.md填写盲评与图质量表；题目审核通过不能替代这两项。
3. 收到标签后：导出独立人评报告和AI裁判偏差敏感性，再更新讨论与结论；原AI评分保留。
4. 最后同步答辩材料，核验正文、摘要、表图、PDF与当前索引。32B不是本轮已经完成的证据，亦不自动扩实验。

当前没有新一轮大规模付费或新题留出集任务；任何后续新运行需另行确认实际规模、成本及冻结状态。
'''
    write(CURRENT/'TASKS.md',tasks)
    review='''# 待人工核验的集中入口

用户已确认两项均尚未完成，当前状态pending。以下是既有评分侧表单，不是新增题库；不重复抽样，也不向被测输入提供。

## 1. 匿名回答与AI裁判校准

优先使用已闭合14B复验回答绑定的[本轮评审说明](../round2_20261020/human_review_round2_001/README.md)、[可读核验包](../round2_20261020/human_review_round2_001/review_packet.md)、[盲化JSON](../round2_20261020/human_review_round2_001/blinded_answers.json)及[填写模板](../round2_20261020/human_review_round2_001/ratings_template.json)。原抽样为全200题中四类各10题，40道问题×完整图/BM25=80份回答；两位评审各80条，共160条记录。人评抽样不等于测试40题，不强行要求四类各10题匹配测试7/6/20/7。

每位评审保存自己的填写文件，逐点填写full/partial/omitted/wrong/unknown、事实pass/fail/unknown、条件判断和理由、reviewer_id，完成后review_status置complete。不给评审方法键、AI标签或其他评审结果；分歧由独立裁决处理。单评审不能宣称双人一致性。

回填后使用源码`human_review_round2.py aggregate --ratings <真实回填JSON> --output <未使用的报告目录>`聚合；先保留原始提交。输出一致率、类别分布、适用kappa/加权kappa、AI/人工EAS差值及分歧。人评仅作独立核验/敏感性，不覆盖原AI评分。旧人评包是此前原运行的样本，不与复验答案混成同一记录。

## 2. 图质量抽查

图未更改，沿用原固定分层样本：[节点50](../round2_20261020/human_review/graph_nodes_50.json)、[关系50](../round2_20261020/human_review/graph_edges_50.json)、[中文别名30](../round2_20261020/human_review/graph_aliases_30.json)、[抽样清单](../round2_20261020/human_review/sampling_manifest.json)。每条含真实来源，填写judgment、error_type、reviewer_id、reason及status；具体允许值见`graph_review.py`与原说明，不以AI自评代替。

所有结论目前pending；合成行为控制通过及200题人工审核均不能作为裁判准确率或图正确率。
'''
    review=review.replace('`graph_review.py`','`graph_review_summary.py`')
    write(CURRENT/'HUMAN_REVIEW.md',review)
    plan=dict(schema='chapter2-publication-plan-v3',updated='2026-10-20',
        status='generation_scoring_complete_human_review_pending',results_index='results.json',
        reporting_split=dict(development_questions=160,test_questions=40,test_groups=5,test_types={'S0':7,'S1':6,'M0':20,'M1':7}),
        dataset_directories={'development':'../../../graduation-datasets/chapter02_knowledge_qa/development_v1_160',
                             'test':'../../../graduation-datasets/chapter02_knowledge_qa/test_v1_40'},
        methods=list(read(CURRENT/'results.json')['methods']),main_methods=9,ablations=4,
        completed_answer_models=['qwen3-8b','qwen3-14b'],comparison_sessions=4600,
        development_sessions=3680,test_sessions=920,original8b_sessions=1600,original14b_sessions=1600,
        additional14b_sessions=1400,graph_bm25_runs_preserved=['original','replicate'],
        generation_complete=True,scoring_complete=True,original_scores_unchanged=True,
        human_judge_validation='pending',graph_quality_validation='pending',
        fixed_query_deliveries=6600,new_question_holdout_cancelled=True,
        future32b='No API/result; separate scope, frozen protocol and cost approval required',
        tasks='TASKS.md',documentation_audit='DOCUMENTATION_AUDIT.md')
    write(CURRENT/'publication-plan.json',json.dumps(plan,ensure_ascii=False,indent=2))
    # Live section2 design is concise; implementation and detailed evidence stay linked.
    research=MATERIALS/'graduation-research'
    p=research/'chapters/chapter02.md'
    write(p,'''# 第2章知识图谱增强专业知识问答

更新时间：2026-10-20。状态：实现、固定查询及既有付费生成评分已完成；统一结果已更新，独立人评/图质量待回填，答辩待同步。

## 定位与方法边界

面向OpenFOAM/blastFoam专业解释、互补资料整合及条件辨析，研究来源组织、自主检索与原文整合。来源图只扫描持久图并核验原文，不依赖外部文本或向量索引；保留来源所属、关系、中文别名和原文锚点，不使用结构化条件字段。完整图已接受，不依据测试结果继续择图。

统一比较九种方法，包括E5和BGE-M3 Dense、两种BM25融合、原文父上下文、基础搜索和直接作答；四项消融考查来源关联、中文别名、关系遍历、上下文交付。新增文本方法无图依赖，仅BGE为新Embedding。不同工具权限和消费者身份必须保留，不称纯后端优势。

## 数据与证据

原200题全部人工审核通过，沿既有身份实体分为160题开发与40题从未参与调参的未见留出测试；依据研究者对旧记录的更正确认，不回写冻结日期。测试14主题、5知识组、四类7/6/20/7；未见题目不等于未见文档。Gold仅评分侧，图、题目、原回答和评分不改。

全部会话4600：8B原1600、14B原1600、新增与复验14B1400；开发3680、测试920。原六方法/两消融是原批次身份，不再代表当前完整范围；8B新增五项未运行，32B无结果。用户已确认总表保留完整图/BM25两次参照，不平均、不择优。

EAS为主指标，严格完整有效率为辅助，失败0分、未知保留边界。原5主比较/2消融与复验4主比较/2消融分别校正。40题5组的保守检验均未确认统计优势；固定查询与自主问答过程分开。独立裁判人评和图质量抽查仍pending，合成控制与题目审核不替代准确率验证。

## 当前入口

- [统一实验、实体问答与机器索引](../../../graduation-experiment-results/chapter2_retrieval/current/README.md)
- [任务顺序与待办](../../../graduation-experiment-results/chapter2_retrieval/current/TASKS.md)
- [工程计划](../../../PrincipiaBlastFoam-DSH/experiments/retrieval_method/KNOWLEDGE_QA_PLAN.md)
- [正文](../../graduation-manuscript/docs/chap02.tex)与[取材](../../graduation-manuscript/CHAPTER2_SOURCES.md)

第3章DSH领域系统和第4章单agent RSI独立论证；冻结设计与原协议不随本说明改写。
''')
    for p in [research/'README.md',research/'OVERVIEW.md',research/'action-plans/README.md',research/'action-plans/chapter01.md',research/'action-plans/chapter05.md',research/'chapters/chapter01.md',research/'chapters/chapter05.md']:
        text=p.read_text(encoding='utf-8')
        text=re.sub(r'(?:200题、)?8B/14B六方法(?:与|及)两(?:项)?消融(?:完成|和论文更新已完成)?',
                    '九种方法/四项消融统一结果已完成，保留E5与BGE及两次参照身份',text)
        text=text.replace('第2章200题、8B/14B六方法及两项消融和论文更新已完成；',
                          '第2章160+40、九方法/四消融统一比较已更新；')
        text=text.replace('第2章8B、14B六方法及两项消融和论文已完成；',
                          '第2章九方法/四消融统一结果已更新，裁判人评与图质量pending；')
        text=text.replace('32B及答辩PPT同步仍待后续。','独立裁判人评与图质量尚待真人回填，答辩待同步，32B无结果。')
        write(p,text)
    write(research/'action-plans/chapter02.md',
        '# 第2章落实方向\n\n更新时间：2026-10-20。方法实现、固定查询、付费生成评分及九方法/四消融统一结果已完成，E5和BGE并列，开发160与测试40实体分开。\n\n接下来完成40题案例链、真实局部图和来源追踪，压缩方法证明及日志；独立裁判人评与图质量等待真人回填，之后写敏感性分析并同步答辩。32B仅在API、研究范围及预算确认后考虑，不是当前已完成结果。\n\n唯一细化待办与进度见[当前任务状态](../../../graduation-experiment-results/chapter2_retrieval/current/TASKS.md)，研究边界见[第2章设计](../chapters/chapter02.md)。不复制冻结协议或另造新题。')
    dataset=WORKSPACE/'graduation-datasets/chapter02_knowledge_qa/README.md'
    write(dataset,'''# 第2章活动题集：开发160题与测试40题

更新时间：2026-10-20。[开发160题](development_v1_160/README.md)与[测试40题](test_v1_40/README.md)为两个实体目录，各自包含model/questions.json及评分侧annotations/evidence。模型只读取ID和自然问题，Gold与必要点不进入构图/检索/回答。

原[formal_v2_200](formal_v2_200/README.md)保留200题原件与标注，69主题、24知识组、四类各50；不是另一套当前活动评测目录。[ID划分及研究者更正确认](split_dev160_test40_20261020.json)沿原基础160与补充40身份，不按成绩重新选题、不改评分。测试40题从未参与调参；测试四类7/6/20/7、14主题、5知识组；未见题目不等于未见文档。

全部200题已逐题人工审核，这与独立裁判/图质量核验仍pending不同。被拒绝的额外新40/60题已清理，不再新增问题。authoring_200只作原题构建来源，不是活动题库；原件中的旧审核阶段保留为冻结快照。

问答和结果统一见[当前实验](../../graduation-experiment-results/chapter2_retrieval/current/README.md)：4600会话、九主方法和四消融，E5/BGE并列；实体按模型、开发/测试、方法及运行身份分开。
''')
    for p in [WORKSPACE/'graduation-datasets/README.md',MATERIALS/'graduation-visualization/README.md',
              MATERIALS/'graduation-visualization/chapter_02_knowledge_graph_retrieval/README.md']:
        text=p.read_text(encoding='utf-8')
        text=re.sub(r'^> 当前实体分集.*\n\n','',text,flags=re.M)
        note='\n\n> 2026-10-20当前口径：160题开发/40题测试；九方法、四消融统一管理，E5与BGE均保留。表图由build_unified_results.py读取current/results.json与两个模型的分集统计生成；旧独立表图脚本仅为历史来源。运行状态、剩余任务以实验current/README.md及TASKS.md为准。\n'
        head,body=text.split('\n',1);write(p,head+note+body)
    manuscript=MATERIALS/'graduation-manuscript'
    overview='''# 毕业论文LaTeX稿件

更新时间：2026-10-20。第2章采用160题开发与40题从未参与调参的未见留出测试；依据研究者对未同步记录的更正，原题与评分不改。

九种方法与四项消融统一呈现，E5和BGE-M3同时保留，完整图/BM25原运行与复验分列，不平均或择优。全部既有会话4600（开发3680、测试920），8B只填真实运行方法。测试5知识组、类型7/6/20/7，全部保守校正比较未确认优势。独立裁判人评/图质量pending，答辩待同步，32B无结果。

入口main.tex，正文docs/，图表assets/chapter2/dev160_test40/；当前生成脚本为build_unified_results.py。唯一正式[main.pdf](main.pdf)和[official_manifest.json](official_manifest.json)在编译检查后同步，PDF页数与来源以正式清单为准，不保留多个论文版本副本。

构建使用make main / make release；本机无make时用latexmk -outdir=build -xelatex main.tex、复制build/main.pdf到main.pdf，再执行tools/release.py。先运行tools/check_chapter2_formal.py并检查渲染页。

[当前取材](CHAPTER2_SOURCES.md) · [共享设计](../graduation-research/chapters/chapter02.md) · [实验与实体记录](../../graduation-experiment-results/chapter2_retrieval/current/README.md) · [剩余任务](../../graduation-experiment-results/chapter2_retrieval/current/TASKS.md)
'''
    write(manuscript/'README.md',overview)
    sources='''# 第2章当前取材与证据入口

更新时间：2026-10-20。论文统一九种主方法/四项消融，开发160题、测试40题；E5与BGE并列，完整图/BM25两次运行保留各自身份，不平均或选高分。

## 活动来源

- [统一方法与运行索引](../../graduation-experiment-results/chapter2_retrieval/current/results.json)：4600会话，完整协议来源与实体入口。
- [8B测试](../../graduation-experiment-results/chapter2_retrieval/current/qwen3-8b/test/summary.json)、[14B测试](../../graduation-experiment-results/chapter2_retrieval/current/qwen3-14b/test/summary.json)，同模型development/分别为开发160题统计。14B by_run区分original与replicate；逐条record保持原评分对象。
- [固定查询分集结果](../../graduation-experiment-results/chapter2_retrieval/current/retrieval-summary.json)：11配置、3档预算；开发5280份交付、测试1320份交付，原始6600交付不重跑。
- [统一表图来源绑定](assets/chapter2/dev160_test40/source-manifest.json)，脚本[build_unified_results.py](../graduation-visualization/chapter_02_knowledge_graph_retrieval/build_unified_results.py)。主表、消融、分类型、过程与资源统一生成；旧model_scales/formal_200是历史快照，不作为当前40题分母。
- [实体记录哈希](../../graduation-experiment-results/chapter2_retrieval/current/physical-records.json)：42243个实际文件，方法/original或replicate/问题ID；原全量执行目录保持不变。
- [两个题集](../../graduation-datasets/chapter02_knowledge_qa/README.md)与[ID及研究者更正](../../graduation-datasets/chapter02_knowledge_qa/split_dev160_test40_20261020.json)。模型只读取自然问题，所有Gold、人评表单均评分侧。
- [正式图绑定](../../graduation-experiment-results/chapter2_retrieval/current/final-graph.json)，[原8B](../../graduation-experiment-results/chapter2_retrieval/current/revision_200_20261019_002/README.md)、[原14B](../../graduation-experiment-results/chapter2_retrieval/current/model14b_200_20261019_002/README.md)、[基础搜索](../../graduation-experiment-results/chapter2_retrieval/current/basic_search_200_20261019_001/README.md)、[新增与复验回执](../../graduation-experiment-results/chapter2_retrieval/round2_20261020/e2e_runs/answer14b_003/README.md)保留冻结协议和真实执行身份。

## 未完成事项与结论限制

用户已确认独立裁判人评与图质量抽查尚未完成，见[集中人工入口](../../graduation-experiment-results/chapter2_retrieval/current/HUMAN_REVIEW.md)。题目人工审核、合成行为控制不等于准确率验证。40题仅5知识组，所有校正检验未确认优势；不沿用原24组显著性，不把未见问题解释成未见文档或物理验证。

继续任务见[TASKS.md](../../graduation-experiment-results/chapter2_retrieval/current/TASKS.md)：案例链、真实图与追踪、方法章节精简、人评敏感性、答辩同步；32B无结果。正式PDF与123等历史源数量均不硬编码，当前发布以official_manifest.json为准。
'''
    write(manuscript/'CHAPTER2_SOURCES.md',sources)
    # Operational plans clearly delegate current status, retaining old execution details as history.
    for p in [PROJECT/'experiments/retrieval_method/KNOWLEDGE_QA_PLAN.md',HERE/'README.md']:
        text=p.read_text(encoding='utf-8');first,body=text.split('\n',1)
        body=body.replace('禁止覆盖历史 `current/` 和 `resources/`。','禁止改写冻结原回执及resources；current活动索引和经核验的复制目录按用户确认统一维护。')
        prefix='\n\n## 当前维护入口（2026-10-20）\n\n九方法与四消融、E5/BGE和两次参照现统一由`current/results.json`及`current/qwen3-8b/`、`current/qwen3-14b/`管理；开发160/测试40实体分开，4600既有会话已评分闭合。人评/图质量pending，具体待办见实验`current/TASKS.md`。下列内容为早期执行与工程细节，不能覆盖当前口径；旧3200会话/六方法仅指原批次。维护脚本unify_current.py处理实体迁移与索引，build_unified_results.py生成全部当前表图。\n\n## 早期执行说明（保留历史身份）\n'
        write(p,first+prefix+body)
    defense=MATERIALS/'graduation-defense/README.md';text=defense.read_text(encoding='utf-8')
    text=text.replace('当前论文已完成8B/14B六方法及两项消融3200会话，','当前论文统一九方法/四消融、E5/BGE与两次核心参照，共4600既有会话，')
    text=text.replace('第2章仅以完整200题新协议评测及全题库分层分析支持论文结论，内部抽样规模、划分、成绩和预算不进入展示。',
        '第2章后续展示采用160题开发/40题测试、九方法/四消融与E5/BGE并列；主表保留两次核心参照，说明5组保守检验未确认优势及独立人评pending。现有PPT仍是旧快照，未因本说明而自动更新。')
    write(defense,text)
    # Archive index redirects to the active catalog rather than acting as a competing entry.
    write(ARCHIVE/'README.md','''# 第二轮冻结来源档案

2026-10-20用户已确认新旧实验统一管理。当前方法总表、实体问答、开发/测试统计、任务与人评状态统一见[实验当前入口](../current/README.md)与[机器索引](../current/results.json)。完整图/BM25两次参照分列，E5和BGE并列，九方法/四消融。

此前split160_40_20261020中的问答复制实体已迁入current/qwen3-8b及qwen3-14b的development/test目录；此处只保留旧分集统计、复制清单和layout-migration.json。当前所有文件来源和迁移位置由current/physical-records.json维护。

本目录保留不可变的原协议、授权、BGE索引、固定查询交付、生成/匿名评分原回执、人评抽样包及dated过程报告，用于追溯，不再作为另一套活动结果。e2e_runs/answer14b_003原1400会话全部闭合；独立人评和图质量等待真实标签。

旧报告中的新60题/40题、等待新题人审、420/280会话计划、全200题作为论文主分母等均属已取消或更正的当时状态；不回写历史报告。已拒绝草稿确已删除。当前仅沿原题身份160+40，不新增题目或付费调用。
''')
    write(ARCHIVE/'split160_40_20261020/README.md',
        '# 历史分集统计快照\n\n问答复制实体已统一迁移到[当前实验](../../current/README.md)，按回答模型、development/test、方法及original/replicate管理。此处保留此前统计与文件清单，layout-migration.json指向新位置；不再作为活动问答入口，不新增或修改原回答评分。')
    # The uploaded plan remains original text with a dated precedence note.
    task=WORKSPACE/'Codex_Chapter2_RAG_Round2_Experiment_Plan.md'
    text=task.read_text(encoding='utf-8');first,body=text.split('\n',1)
    note='\n\n> 2026-10-20执行修订（用户最新确认优先）：不再新造60/40题，原200题实体拆为开发160与从未参与调参的未见留出测试40；原记录范围由研究者更正。九方法总表必须同时保留E5和BGE，完整图/BM25两次参照分列，结果统一由`graduation-experiment-results/chapter2_retrieval/current/`维护。付费生成评分已闭合4600既有会话；独立裁判人评与图质量用户确认仍pending。以下保留原任务书文本，原第10节新造留出计划不再执行，具体当前验收与待办见`current/TASKS.md`。\n'
    write(task,first+note+body)
    conflicts=[
        dict(topic='新旧基线分节',resolution='已合为九方法总表，同时保留E5/BGE；四消融统一分析'),
        dict(topic='两次graph/BM25结果',resolution='用户确认保留原/复验两行，不平均或选优；消费者差异披露'),
        dict(topic='独立人工核验',resolution='用户明确尚未完成；80回答两评审160记录与图50/50/30保持pending'),
        dict(topic='3200与4600会话',resolution='3200为原批次，额外1400已完成；当前4600，开发3680/测试920'),
        dict(topic='200题主分母和160/40',resolution='200仅原件/全量执行身份，当前测试40、开发160，测试实际5组，所有校正不显著'),
        dict(topic='新60/40题及420/280会话',resolution='用户已撤销并删除；不恢复'),
        dict(topic='旧独立结果目录',resolution='复制实体迁入current两模型分集目录，旧位置只保留统计来源与迁移说明；原冻结回执不改'),
        dict(topic='旧检索预算6000/12000/24000',resolution='为早期计划；实际冻结固定查询为2000/4000/6000，6600交付；当前文档按实测纠正'),
        dict(topic='答辩已同步',resolution='只有README纠正，现有PPT/PDF仍旧快照，明确待同步'),
        dict(topic='32B',resolution='无API/结果；不自动填分或发起新收费批次')]
    audit=dict(schema='chapter2_live_documentation_reconciliation_v1',updated_utc=datetime.now(timezone.utc).isoformat(),
               changes=changes,conflicts=conflicts,frozen_protocols_modified=False,
               current_user_decisions=['接受：统一表格，保留两次参照结果','尚未完成，保留待办并整理表单'])
    write(CURRENT/'documentation-maintenance.json',json.dumps(audit,ensure_ascii=False,indent=2))
    rows=['# 当前文档冲突审查','', '更新时间：2026-10-20。以下仅纠正活动文档；冻结协议、原评分与dated过程报告保留原身份。', '', '|发现的冲突|处理与依据|','|---|---|']
    rows += ['|'+x['topic']+'|'+x['resolution']+'|'for x in conflicts]
    rows += ['', '用户本轮已确认两次参照的展示方式及人评仍pending；当前没有尚未求证的阻断性事实。未来新发现的研究事实冲突应先求证，不擅自改分、补造人审或重写冻结记录。', '',
             '当前权威入口：results.json管方法/运行，publication-plan.json管机器状态，TASKS.md管待办，HUMAN_REVIEW.md管真人核验。更新脚本必须同步这些入口及共享设计、稿件和答辩的实际状态。', '',
             '具体文件与修改前后SHA256见documentation-maintenance.json；历史报告通过档案README标明为当时状态，不把快照文字当成当前未执行任务。']
    write(CURRENT/'DOCUMENTATION_AUDIT.md','\n'.join(rows))
    print('Reconciled live docs:',len(changes),'files; no frozen scores/protocols modified')


if __name__=='__main__':main()
