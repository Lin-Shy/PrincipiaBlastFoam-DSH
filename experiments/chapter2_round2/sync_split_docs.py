"""Update current design/entry points; frozen protocols and scored rows unchanged."""
from common import *
from split_existing200 import SPLIT,OUT

def edit(path,old,new):
    text=path.read_text(encoding='utf-8')
    if old not in text:
        if new in text:return
        raise ValueError('missing current-doc anchor: '+str(path))
    path.write_text(text.replace(old,new),encoding='utf-8')

def prepend(path,section):
    text=path.read_text(encoding='utf-8')
    if section in text:return
    head,body=text.split('\n',1);path.write_text(head+'\n\n'+section+'\n'+body,encoding='utf-8')

def main():
    materials=WORKSPACE/'graduation-thesis-materials';research=materials/'graduation-research';manuscript=materials/'graduation-manuscript'
    role='论文统一使用原200题的160/40划分：原基础160题为开发与参数调优集，原补充40题为从未参与调参的未见留出测试集。研究者于2026-10-20明确更正此前未同步记录，此确认及既有ID清单见`graduation-datasets/chapter02_knowledge_qa/split_dev160_test40_20261020.json`；不按成绩选题，不改原始回答或评分。正文主结果分母40，开发结果分母160；测试四类7/6/20/7题、14主题、5知识组，不能沿用全200题24组显著性。未见题目不等于未见文档，划分补录不回写冻结时间。'
    for path in [WORKSPACE/'AGENTS.md',WORKSPACE/'graduation-datasets/AGENTS.md',manuscript/'AGENTS.md']:
        edit(path,'## 第2章当前数据范围（2026-10-19用户更新）','## 第2章当前数据范围（2026-10-20用户更正）')
        edit(path,'论文统一使用“200题专业知识问答集”，评价以全部题目及预定义类型、知识组为范围。抽样仅用于内部迭代，不进入论文或公开答辩，不宣称既有暴露题目的未见泛化。',role)
        edit(path,'失败计0、未知保留上下界，全部200题保留分母。','失败计0、未知保留上下界；论文测试40题与开发160题分别保留完整分母，原全200题运行记录不改。')
        prepend(path,'> 2026-10-20最新指令：取消并清理第二轮额外新建的40/60题草稿，唯一题库仍为formal_v2_200。沿用其已有基础160/补充40身份及原回答评分；研究者已确认40题未参与调参，并更正旧记录。原全量运行与历史协议身份继续保留。')
    for path in [research/'README.md',research/'OVERVIEW.md',research/'chapters/chapter02.md',research/'chapters/chapter01.md',research/'chapters/chapter05.md',research/'action-plans/chapter02.md']:
        text=path.read_text(encoding='utf-8').replace('更新时间：2026-10-19','更新时间：2026-10-20')
        text=text.replace('以全部200题完成论文评测，抽样仅用于内部迭代','以160题开发与40题未见留出测试分别报告，不新增题目或修改原始评分')
        text=text.replace('第2章绪论、摘要及总结以全200题正式AI评分与统计为依据，保留固定题库和测量边界','第2章绪论、摘要及总结采用160题开发与40题未见留出测试，复用原正式评分并重新汇总，保留测量边界')
        text=text.replace('失败计0、未知保留上下界，全部200题保留分母','失败计0、未知保留上下界，开发160题和测试40题分别保留完整分母')
        text=text.replace('题库已暴露，结果不外推为未见泛化','研究者已更正此前未同步的调参范围：仅160题参与调优，40题为未见留出测试；不推断未见文档泛化')
        text=text.replace('14B图谱相对基础搜索和直接作答的优势获得当前保守统计支持，相对BM25尚未确认；8B未确认稳定优势，两项消融也未确认稳定收益','40题测试集中完整图的EAS为8B32.3–38.1、14B62.0分；5知识组上的主比较和两消融均未确认稳定统计优势。原全200题统计保留原身份，不能沿用为测试结论')
        path.write_text(text,encoding='utf-8')
        prepend(path,'## 160题开发与40题未见留出测试（当前口径）\n\n原200题及既有评分不变；基础160题用于开发调参，补充40题为从未参与调参的未见留出测试集，依据研究者2026-10-20对未同步记录的更正。沿用已调优设置，不新增题目或调用。正文与表图已按测试40题、5知识组重新汇总；四类7/6/20/7，开发160题另列。原全200题运行计数属于执行身份，不是当前测试分母。32B及答辩PPT同步仍待后续。\n\n[唯一划分清单](../../../graduation-datasets/chapter02_knowledge_qa/split_dev160_test40_20261020.json)；项目级路径以第2章维护入口为准。')
    chapter=research/'chapters/chapter02.md'
    edit(chapter,'再对全部题目取均值','再对对应开发或测试子集全部题目取均值')
    paths=[WORKSPACE/'graduation-datasets/chapter02_knowledge_qa/README.md',WORKSPACE/'graduation-datasets/README.md']
    for path in paths:prepend(path,'## 当前划分：开发160题／未见留出测试40题\n\n唯一200题及其标注不改。使用formal_v2_200/dataset.json已有基础160与new_ids40身份：[划分与研究者确认](chapter02_knowledge_qa/split_dev160_test40_20261020.json)。40题从未参与调参，直接复用既有回答和评分；本次只补录此前未同步的角色。第二轮额外构造的40/60题已按用户要求清理，不再等待其人审或运行。测试四类7/6/20/7题，5知识组；不按方法成绩重选。')
    edit(WORKSPACE/'graduation-datasets/chapter02_knowledge_qa/README.md','(chapter02_knowledge_qa/split_dev160_test40_20261020.json)','(split_dev160_test40_20261020.json)')
    for path in [manuscript/'README.md',manuscript/'CHAPTER2_SOURCES.md']:
        prepend(path,'## 当前160/40口径（2026-10-20）\n\n采用160题开发调参与40题从未参与调参的未见留出测试，研究者对未同步历史记录的更正确认见[划分清单](../../graduation-datasets/chapter02_knowledge_qa/split_dev160_test40_20261020.json)。原题、回答、评分和全量统计文件不改，新增调用0。当前正文结果、图表、摘要与总结以40题、5知识组为测试分母；开发160题另列。40题上8B完整图EAS32.3–38.1、14B62.0；保守校正检验均未确认统计优势。\n\n当前资产：[dev160_test40](assets/chapter2/dev160_test40/source-manifest.json)，生成脚本为build_split_results.py；旧model_scales/formal_200资产与以下全量执行说明保留历史身份。第二轮新造40/60题已清理。PDF及来源清单在本次编译后同步；答辩待后续。')
    for path in [materials/'graduation-visualization/README.md',materials/'graduation-visualization/chapter_02_knowledge_graph_retrieval/README.md']:
        prepend(path,'## 当前论文图表口径：160题开发／40题未见留出测试\n\n使用build_split_results.py从原逐题评分的固定ID子集生成assets/chapter2/dev160_test40/。测试每方法40题、四类7/6/20/7、5知识组；开发每方法160题另列。既有build_model_scale_results.py及model_scales/资产保留原全200题身份，不覆盖历史评分。研究者已更正未同步调参记录，确认40题未参与调参；不新增问答或评分调用。')
    current=CURRENT/'README.md'
    prepend(current,'## 当前报告范围：160题开发／40题未见留出测试\n\n研究者2026-10-20明确更正此前未同步记录：原基础160题用于开发与调参，原补充40题从未参与调参，作为未见留出测试。原200题及3200会话证据保持原样，只按已有ID重汇总。测试每模型320会话、开发1280会话；测试5知识组，主比较与两消融均未确认统计优势。\n\n[划分与更正确认](../../../graduation-datasets/chapter02_knowledge_qa/split_dev160_test40_20261020.json) · [40题8B统计](../round2_20261020/split160_40_20261020/8b/test/summary.json) · [40题14B统计](../round2_20261020/split160_40_20261020/14b/test/summary.json)。以下为原全200题执行、批次与历史统计说明，不作为当前40题分母或显著性。第二轮额外新造的40/60题已清理。')
    publication=CURRENT/'publication-plan.json';plan=read(publication)
    plan.update(updated='2026-10-20',reporting_split=dict(development_questions=160,test_questions=40,test_groups=5,test_types=read(SPLIT)['test']['types'],
        split_file=str(SPLIT.relative_to(WORKSPACE)),split_sha256=sha(SPLIT),tuning_history='Researcher correction: only original160 used for tuning; original40 unseen to tuning',
        new_generation=0,new_judging=0,original_sessions_and_scores_unchanged=True,primary_test_conclusion='No statistical superiority established under actual5-group conservative tests'))
    publication.write_text(json.dumps(plan,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    for path in [ARCHIVE/'README.md',HERE/'README.md']:
        prepend(path,'## 当前指令覆盖：取消新造题，采用原200题的160/40划分\n\n新增40题与60题草稿及专属流程已清理；旧人审等待和280会话计划取消。研究者已明确更正未同步记录，原基础160题用于调参、原补充40题从未参与调参，作为未见留出测试。只引用原题ID与既有回答评分，不新增题目或调用。当前划分和统计位于split160_40_20261020，论文以测试40题为主、开发160题另列；以下为旧过程快照。既有1400会话付费评分继续完成其原任务，不为新题重跑。')
    print('Synced current instructions, dataset entry, shared design, manuscript/figure entries and publication reporting scope')

if __name__=='__main__':main()
