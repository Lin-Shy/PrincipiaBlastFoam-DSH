"""Current entry points and final audit for physical160/40 reuse; no API calls."""
from datetime import datetime,timezone
from common import *
from split_existing200 import SPLIT,OUT
from materialize_split import DATA_DIRS

def edit(path,old,new):
    text=path.read_text(encoding='utf-8')
    if old in text:path.write_text(text.replace(old,new),encoding='utf-8')

def documentation():
    materials=WORKSPACE/'graduation-thesis-materials';manuscript=materials/'graduation-manuscript'
    for path in [materials/'graduation-research/README.md',materials/'graduation-research/OVERVIEW.md']:
        edit(path,'(../../../graduation-datasets/chapter02_knowledge_qa/split_dev160_test40_20261020.json)','(../../graduation-datasets/chapter02_knowledge_qa/split_dev160_test40_20261020.json)')
    for path in [manuscript/'docs/abstract.tex',HERE/'update_split_manuscript.py']:
        for old,new in [('spans69','spans 69'),('and24','and 24'),('groups:160','groups: 160'),('and40','and 40'),('anonymous14B','anonymous 14B'),('the40-question','the 40-question'),('is32.3','is 32.3'),('with8B','with 8B'),('and62.0','and 62.0'),('with14B;14B','with 14B; 14B'),('is37.5','is 37.5'),('versus20.0','versus 20.0')]:edit(path,old,new)
    for name in ['abstract.tex','chap02.tex','chap05.tex']:
        for old,new in [('62.0--62.0','62.0'),('37.5--37.5','37.5')]:edit(manuscript/'docs'/name,old,new)
    edit(manuscript/'docs/chap01.tex','全题库比较区分依据送达与回答完成','开发与测试分开报告，区分依据送达与回答完成')
    appendix=manuscript/'docs/appendix_ch02.tex'
    old='ID及确认依据位于\\path{graduation-datasets/chapter02_knowledge_qa/split_dev160_test40_20261020.json}'
    new='题集实体分别位于\\path{chapter02_knowledge_qa/development_v1_160}和\\path{chapter02_knowledge_qa/test_v1_40}；各自保存\\path{model/questions.json}、\\path{scoring/annotations.json}和\\path{scoring/evidence.json}。ID及确认依据位于\\path{graduation-datasets/chapter02_knowledge_qa/split_dev160_test40_20261020.json}'
    edit(appendix,old,new)
    edit(appendix,'派生统计位于\\path{round2_20261020/split160_40_20261020}。','原始问答和评分也按模型与子集实体存放于\\path{round2_20261020/split160_40_20261020/<model>/development}及\\path{<model>/test}，各自含\\path{generation/}、\\path{scoring/}、\\path{scoring_payloads/}和统计，不混用开发与测试记录；原件哈希映射见各目录\\path{physical-records.json}。')
    current=ARCHIVE/'README.md'
    content='''# 第2章第二轮与160/40实体划分

## 当前交付

原200题实体拆分为开发160题和未见留出测试40题，采用已有调优设置；研究者已更正此前未同步的调参记录，确认40题从未参与调参。没有构造新题、重新生成或重新评分；此前已获批的1400会话现已闭合。

- [160题开发集](../../../graduation-datasets/chapter02_knowledge_qa/development_v1_160/README.md)
- [40题测试集](../../../graduation-datasets/chapter02_knowledge_qa/test_v1_40/README.md)
- [实体问答与评分总入口](split160_40_20261020/README.md)：8B、原14B、第二轮14B分别维护development/和test/；每部分按方法/问题存放原始回答、请求、评分和统计。
- [ID划分及研究者更正确认](../../../graduation-datasets/chapter02_knowledge_qa/split_dev160_test40_20261020.json)
- [阶段报告](reports/physical_split_delivery_006.md)、[已删除拒绝草稿的哈希清单](audit/cancelled_new_holdout_cleanup_005.json)

新增40/60题草稿和专属流程已实际删除，原等待人审、280会话计划取消。原formal_v2_200和全量实验目录仅作保留原件；当前实体分集为上方两个目录。固定划分保留160/40原身份，不按成绩重新选题。原全量回答、评分、图与语料不改。

## 结论与范围

40题测试有14主题、5知识组，四类7/6/20/7，非均衡抽样。原批次完整图EAS为8B32.3–38.1、14B62.0；第二轮14B本批完整图57.4–60.5。各测试比较均未通过当前5知识组保守校正检验；原全200题的24组显著性不沿用。未见题目不等于未见文档，AI裁判准确率仍无独立人工验证。

论文正文、摘要、绪论、总结、附录及表图按160+40同步。旧全量资产、冻结协议与历史过程报告保留原身份，不作为当前测试分母或待办。

## 原离线阶段与原始执行

11方法×200题×3预算的6600固定查询交付见[evaluation/final_001](evaluation/final_001/retrieval_report.md)，属于原全量归档。14B第二轮原1400会话的闭合回执见[answer14b_003](e2e_runs/answer14b_003/README.md)。当前测试只用其中40题，开发仅用其余160题。
'''
    current.write_text(content,encoding='utf-8')
    (OUT/'README.md').write_text('''# 按原题身份实体分开的历史问答

|模型批次|开发160题|未见留出测试40题|
|---|---|---|
|Qwen3-8B原批次|[1280会话](8b/development/README.md)|[320会话](8b/test/README.md)|
|Qwen3-14B原批次|[1280会话](14b/development/README.md)|[320会话](14b/test/README.md)|
|Qwen3-14B第二轮|[1120会话](round2_14b/development/README.md)|[280会话](round2_14b/test/README.md)|

每个单元均为实体目录：generation/、scoring/、scoring_payloads/按方法/问题ID分开；session-metrics.json/.csv及summary.json只含该子集。physical-records.json逐文件绑定原位置与SHA256，实际复制，不使用硬链接或符号链接。

原200题全量目录保留只读，原始协议在各子集provenance/中保留全量执行身份，协议里的200/1600计数不是该子集分母。各批参照不合并，不把复用文件当作新增调用。题集实体位于development_v1_160和test_v1_40；split_dev160_test40_20261020.json只作ID与研究者更正确认索引，并非唯一分割形式。
''',encoding='utf-8')
    for path in [WORKSPACE/'graduation-datasets/chapter02_knowledge_qa/README.md',WORKSPACE/'graduation-datasets/README.md',manuscript/'README.md',manuscript/'CHAPTER2_SOURCES.md',WORKSPACE/'AGENTS.md',WORKSPACE/'graduation-datasets/AGENTS.md',manuscript/'AGENTS.md']:
        text=path.read_text(encoding='utf-8');head,body=text.split('\n',1)
        note='\n\n> 当前实体分集为`graduation-datasets/chapter02_knowledge_qa/development_v1_160/`与`test_v1_40/`，各自有model/和scoring/；历史问答在`round2_20261020/split160_40_20261020/<model>/development/`与`test/`实体分开。原formal_v2_200和全量运行仅保留为原件，JSON划分清单只是索引。\n'
        if note.strip()not in text:path.write_text(head+note+body,encoding='utf-8')
    src=HERE/'README.md';text=src.read_text(encoding='utf-8')
    start=text.find('## 2026-10-20执行续报');end=text.find('源码与测试仅在本目录维护')
    if 0<=start<end:text=text[:start]+'## 实体划分维护\n\n`split_existing200.py`按原ID汇总，`materialize_split.py`建立160/40题集与所有历史问答实体目录；旧holdout40/60构造与执行流程已删除。当前1400付费评分已闭合，无新增题目或付费调用。详见归档README。\n\n'+text[end:]
    src.write_text(text,encoding='utf-8')
    status=ARCHIVE/'reports/paid_postprocess_status.json'
    status.write_text(json.dumps(dict(status='superseded_by_physical160_40_delivery',paid_sessions=1400,new_draft_holdouts_cancelled=True,physical_split=str(OUT.relative_to(WORKSPACE)),updated_utc=datetime.now(timezone.utc).isoformat()),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Current entries point to physical datasets and separated raw QA records')

def audit():
    before=read(ARCHIVE/'audit/historical_before.json');allowed=[];protected={}
    for name,h in before.items():
        if name.startswith('graduation-thesis-materials/graduation-manuscript/')or name in ['graduation-experiment-results/chapter2_retrieval/current/README.md','graduation-experiment-results/chapter2_retrieval/current/publication-plan.json']:allowed.append(name)
        else:protected[name]=h
    changed=[name for name,h in protected.items()if not(WORKSPACE/name).is_file()or sha(WORKSPACE/name)!=h]
    save(ARCHIVE/'audit/physical_split_originals_preserved_006.json',dict(protected_frozen_data_files=len(protected),changed_or_missing=changed,
        explicitly_authorized_manuscript_and_current_doc_scope=len(allowed),protected_originals_unchanged=not changed,
        notice='Original formal200, corpus, graphs, generations, scoring and frozen protocols preserved; manuscript and current README/reporting plan edits expressly authorized'))
    if changed:raise ValueError('original experimental data changed')
    from qa_outputs import receipt_usage
    gen=ARCHIVE/'e2e_runs/answer14b_003'
    usage={}
    for name,paths in [('generation',sorted(gen.glob('*/generation/*/requests/*.json'))),('judge',sorted((gen/'scoring_001/sessions').glob('*/*/requests/*.json')))]:usage[name],_=receipt_usage(paths)
    save(ARCHIVE/'reports/actual_round2_usage_006.json',dict(sessions=1400,usage=usage,price='Private proxy actual prices not available; no invented currency estimate',new_calls_for_partition=0))
    print('Preserved original frozen-data files:',len(protected),'changed:',len(changed))

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('action',choices=['documentation','audit']);a=p.parse_args();documentation()if a.action=='documentation'else audit()
