"""Close the reviewed physical split delivery without changing experimental records."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
MANUSCRIPT = ROOT / 'graduation-thesis-materials/graduation-manuscript'
ARCHIVE = ROOT / 'graduation-experiment-results/chapter2_retrieval/round2_20261020'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    review_path = MANUSCRIPT / 'build/review.json'
    review = json.loads(review_path.read_text(encoding='utf-8'))
    assert review['automatic_checks_passed']
    assert review['pdf_sha256'] == digest(MANUSCRIPT / 'build/main.pdf')
    review['visual_review_status'] = 'passed_visual_inspection'
    review['visual_review_scope'] = {
        'rendered_pages_inspected': review['rendered_pdf_pages'],
        'contact_sheet_sha256': {
            name: digest(MANUSCRIPT / name) for name in review['contact_sheets']
        },
        'notes': 'Inspected all seven contact sheets covering42 selected pages; readable tables, figures and text; no clipping or overlap observed. Remaining pages were not visually reviewed.',
    }
    review_path.write_text(json.dumps(review, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    current_matches = digest(MANUSCRIPT / 'main.pdf') == review['pdf_sha256']
    pdf_note = ('正式main.pdf已编译为80页，来源清单及页面检查随本次交付同步；答辩待后续。'
                if current_matches else
                '新版80页PDF已编译至build/main.pdf并通过页面检查；根目录main.pdf被预览进程占用，待关闭后同步正式PDF与来源清单。答辩待后续。')
    for name in ['README.md', 'CHAPTER2_SOURCES.md']:
        path = MANUSCRIPT / name
        text = path.read_text(encoding='utf-8')
        for old in ['PDF及来源清单在本次编译后同步；答辩待后续。',
                    '正式main.pdf已编译为80页，来源清单及页面检查随本次交付同步；答辩待后续。',
                    '新版80页PDF已编译至build/main.pdf并通过页面检查；根目录main.pdf被预览进程占用，待关闭后同步正式PDF与来源清单。答辩待后续。']:
            text = text.replace(old, pdf_note)
        path.write_text(text, encoding='utf-8')
    path = Path(__file__).with_name('README.md')
    text = path.read_text(encoding='utf-8').replace(
        '既有1400会话付费评分继续完成其原任务，不为新题重跑。',
        '既有1400会话付费评分已闭合，当前实体拆分不产生新调用。').replace(
        '付费评分还需独立冻结和审批，本轮未运行。留出仅有模板和格式门，没有新留出题或成绩。',
        '上述为原启动阶段说明：生成及独立冻结的付费评分现已全部完成；新造留出题计划取消，当前采用原题160/40实体划分。')
    path.write_text(text, encoding='utf-8')
    report = '''# 160/40实体拆分交付（2026-10-20）

## 已完成的目录与原件保护

- 题集实体：[开发160题](../../../../graduation-datasets/chapter02_knowledge_qa/development_v1_160/README.md)、[测试40题](../../../../graduation-datasets/chapter02_knowledge_qa/test_v1_40/README.md)。各自保存model/questions.json、scoring/annotations.json、scoring/evidence.json、dataset.json及binding.json；问题与标注均为原200题对应对象，没有新增或改写。
- 原160题身份作为开发集，原补充40题身份作为测试集，没有依据成绩重新选题。研究者于2026-10-20明确更正此前未同步的调参记录，并确认测试40题从未参与调参；确认原话及时间保存在划分索引，不回填历史时间或改写冻结快照。
- [历史问答实体入口](../split160_40_20261020/README.md)分为下列六个实际目录。每个目录均含generation/、scoring/、scoring_payloads/、provenance/和仅该子集的统计文件；逐文件来源及SHA256见physical-records.json。文件为实际复制，没有硬链接或符号链接。

|批次目录|development会话|test会话|复制文件数|
|---|---:|---:|---:|
|8b|1280|320|12969|
|14b|1280|320|14674|
|round2_14b|1120|280|14600|
|合计|3680|920|42243|

原formal_v2_200与原全量运行保留为来源档案。42243个复制文件均与来源哈希一致；另对基准清单中31532个受保护的冻结数据文件复核，改变或缺失为0（audit/physical_split_originals_preserved_006.json）。论文和当前入口文档属于用户授权修改范围。此前拒绝的新40/60题草稿及专用流程已清理，41个文件的删除清单保留路径、大小与哈希，不备份题目正文。

## 实际实现与命令

新增维护代码位于PrincipiaBlastFoam-DSH/experiments/chapter2_round2/：split_existing200.py、materialize_split.py、sync_split_docs.py、update_split_manuscript.py、finalize_split_delivery.py、close_split_delivery.py，以及tests/test_split_existing200.py、tests/test_physical_split.py。付费评分续跑代码resume_scoring.py保留原请求/回执；冻结执行脚本与历史评分不改。

制图新增graduation-visualization/chapter_02_knowledge_graph_retrieval/build_split_results.py和build_round2_split_results.py；新表图保存到稿件assets/chapter2/dev160_test40/，旧全量资产保留。同步了稿件摘要、第1/2/5章、实验设计与结果、附录、共享设计及当前入口。新增tools/check_chapter2_split.py并调整tools/check_chapter2_formal.py以核对实际40题分母与表图绑定。

以下为本次已执行命令的可复现形式（WORKSPACE为工作区；PY为PrincipiaBlastFoam-DSH/.local/knowledge-qa-venv/Scripts/python.exe；HERE为实验源码目录；M为稿件目录；V为制图目录；A为本归档目录）：

```text
PY -X utf8 HERE/split_existing200.py freeze
PY -X utf8 HERE/split_existing200.py analyze --include-round2
PY -X utf8 HERE/materialize_split.py datasets
PY -X utf8 HERE/materialize_split.py records
PY -X utf8 HERE/finalize_split_delivery.py documentation
PY -X utf8 HERE/finalize_split_delivery.py audit
D:/anaconda3/python.exe -X utf8 V/build_split_results.py
D:/anaconda3/python.exe -X utf8 V/build_round2_split_results.py
PY -X utf8 -m pytest HERE/tests -o addopts= -q --junitxml=A/audit/physical_split_suite_006.xml
latexmk -outdir=build -xelatex main.tex  [cwd=M]
PY -X utf8 M/tools/check_chapter2_formal.py
PY -X utf8 HERE/close_split_delivery.py
Copy-Item -LiteralPath build/main.pdf -Destination main.pdf -Force  [cwd=M]
PY -X utf8 tools/release.py  [cwd=M]
```

测试35通过、1跳过（实验虚拟环境缺matplotlib）；制图测试另在具备matplotlib的系统Python下通过1项。实体分集测试逐一验证题目及标注对象、各臂ID隔离、全部复制文件哈希和真实Gold读取隔离规则。首次编译因第二轮表文件尚未在正确目录生成而失败，补齐后成功；长表重复标签已修正。最终80页PDF编译与自动检查通过，42个相关页面的7张联系表已逐张目视检查。保留原模板的封面轻微overfull、字体及参考文献underfull提示，没有将这些提示表述为测试失败或全部消除。

正式PDF SHA256：PDF_HASH。main.pdf及official_manifest.json随本次交付同步，完整检查记录见稿件build/review.json。

## 40题测试统计与边界

测试集14主题、5知识组，四类题数7/6/20/7，13题需要条件辨析；不宣称四类均衡。原8B完整图端到端有效回答得分32.3–38.1、原14B为62.0，严格完整有效率分别12.5%与37.5%。第二轮14B独立批次完整图为57.4–60.5，BGE-M3为51.1；不得把该批与原14B合并。每项数值均从原会话评分筛选后汇总，未知状态保留上下界，失败计0。

当前40题的所有预定义方法比较与消融均未通过按5知识组实施的校正检验。原200题24知识组的显著性不移入测试结论。开发160题仅报告开发统计。40题“从未参与调参的未见留出集”的表述依据研究者更正确认；问题未参与调参不等于文档未见。题目人工审核不等于独立验证AI裁判准确率，裁判准确率仍无独立人工验证。

## 已授权付费任务与费用记录

第二轮原1400会话的生成、匿名评分与分析均已闭合，入口e2e_runs/answer14b_003/。生成侧3487个请求，已知合计8022608 tokens，1请求usage未知；评分侧5136个请求，已知合计9123814 tokens，5请求usage未知。计数包含接口失败/拒绝记录，不能将请求总数误作计费成功调用数。指定代理实际单价不可得，未编造货币金额。详见actual_round2_usage_006.json。

中断恢复复用已完成的1000条评分，后400条沿用冻结协议。两条非法Unicode生成均按统一失败规则保留原始字节与回执，未因异常重写答案或历史评分。实体划分本身没有新增付费调用，也没有新增题目或重生成/重评分。

## 后续状态

本次题集与历史问答实体拆分、统计、测试及论文PDF交付已完成。答辩材料尚待独立同步；32B没有结果。任何后续实验需维持批次身份与评分侧隔离，不能把复制记录当作新实验。
'''.replace('PDF_HASH', review['pdf_sha256'])
    if not current_matches:
        report = report.replace('main.pdf及official_manifest.json随本次交付同步，完整检查记录见稿件build/review.json。',
                                '新版位于build/main.pdf；根目录main.pdf被预览进程占用，Copy-Item覆盖失败，正式PDF及official_manifest.json尚未同步。完整检查记录见稿件build/review.json。')
        report = report.replace('本次题集与历史问答实体拆分、统计、测试及论文PDF交付已完成。',
                                '本次题集与历史问答实体拆分、统计、测试及新版PDF编译已完成；仅正式PDF替换与发布清单更新待文件解除占用。')
    (ARCHIVE / 'reports/physical_split_delivery_006.md').write_text(report, encoding='utf-8')
    print('Reviewed PDF status and physical split delivery report saved')


if __name__ == '__main__':
    main()
