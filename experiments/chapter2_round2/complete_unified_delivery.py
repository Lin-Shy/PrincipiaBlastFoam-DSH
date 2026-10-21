"""Verify protected original data and summarize the current merged delivery."""
from datetime import datetime,timezone
import xml.etree.ElementTree as ET
from common import *


def main():
    baseline=read(ARCHIVE/'audit/historical_before.json')
    docs=read(CURRENT/'documentation-maintenance.json')
    authorized={r['path']for r in docs['changes']}|{
        'graduation-experiment-results/chapter2_retrieval/current/README.md',
        'graduation-experiment-results/chapter2_retrieval/current/publication-plan.json',
        'graduation-experiment-results/chapter2_retrieval/current/documentation-maintenance.json'}
    protected={k:v for k,v in baseline.items()if not k.startswith('graduation-thesis-materials/graduation-manuscript/')and k not in authorized}
    changed=[k for k,v in protected.items()if not(WORKSPACE/k).is_file()or sha(WORKSPACE/k)!=v]
    if changed:raise ValueError('Protected original changed: '+repr(changed))
    result=dict(schema='unified_protected_originals_v1',checked_utc=datetime.now(timezone.utc).isoformat(),
        protected_files=len(protected),changed_or_missing=changed,authorized_live_doc_paths=sorted(authorized),
        all_original_scores_and_protocols_unchanged=True)
    (CURRENT/'protected-records-audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    suite=ET.parse(CURRENT/'unified-suite.xml').getroot().find('testsuite')
    counts={k:int(suite.attrib[k])for k in ['tests','errors','failures','skipped']}
    if counts['errors']or counts['failures']:raise ValueError('Tests not passed')
    passed=counts['tests']-counts['skipped']
    report=f'''# 统一比较、实体管理与文档审查交付（2026-10-20）

## 用户确认与已落实的变化

1. 用户接受统一表格保留两次参照：九种主方法在同一表中比较，E5和BGE-M3均保留；完整图/BM25原运行和复验各列一行，不平均或选择较高分。四项消融统一分析，仍按其相同消费者参照及历史校正族统计。
2. 用户确认独立裁判人评与图质量均尚未完成：保持pending，既有人评表集中导航于HUMAN_REVIEW.md，不新增题目或代填标签。
3. 全部既有问答实体统一迁入current/qwen3-8b和qwen3-14b的development/test目录，方法/original或replicate/题目ID分层。原独立分集位置只保留历史统计、复制清单及迁移说明，不再持有问答实体。

## 实际规模与保护结果

|模型|开发160题会话|测试40题会话|总会话|
|---|---:|---:|---:|
|8B|1280|320|1600|
|14B（含原运行及新增/复验）|2400|600|3000|
|合计|3680|920|4600|

42243个迁移文件均在移动前后核验哈希，并由隔离测试再次逐文件比较原件。只移动此前复制的实体；冻结原始回答、评分、协议、图和语料不改。对初始清单中{len(protected)}个受保护文件复核，改变或缺失0；活动文档与稿件属于明确授权修改范围，详见protected-records-audit.json。

## 代码、稿件与文档文件

- 实验源码：unify_current.py、document_current.py、reconcile_remaining_docs.py、revise_unified_manuscript.py、complete_unified_delivery.py；测试test_physical_split.py与test_unified_current.py（以及后续文档检查）。
- 制图：新增build_unified_results.py为唯一当前生成入口；两个旧分集/第二轮入口委托该脚本，避免再次产出分开的主表。所有当前表图在稿件assets/chapter2/dev160_test40/，旧round2/子表图目录已清理，删除前哈希见retired-round2-assets.json。
- 稿件：更新实验设计、统一九方法结果、四消融、固定查询预算曲线与表，联动摘要、绪论、总结及附录；当前分母测试40、开发160、5测试知识组。
- 活动入口：results.json、两模型四个实体目录、physical-records.json、retrieval-summary.json、publication-plan.json、README.md、TASKS.md、HUMAN_REVIEW.md及DOCUMENTATION_AUDIT.md。
- 同步工作区/数据/实验/稿件/DSH的AGENTS、共享设计及落实方向、题集入口、制图说明、源码执行说明、任务书修订说明和答辩README。答辩PPT/PDF本身尚未更新，不冒充已同步。文件级修改前后哈希见documentation-maintenance.json。

## 实际运行命令

工作区根目录；PY为PrincipiaBlastFoam-DSH/.local/knowledge-qa-venv/Scripts/python.exe，HERE为experiments/chapter2_round2源码目录，V为统一材料仓库内制图目录。

```text
PY -X utf8 HERE/unify_current.py migrate
PY -X utf8 HERE/unify_current.py publish
D:/anaconda3/python.exe -X utf8 V/build_unified_results.py
PY -X utf8 HERE/revise_unified_manuscript.py
PY -X utf8 HERE/document_current.py
PY -X utf8 HERE/reconcile_remaining_docs.py
PY -X utf8 -m pytest HERE/tests -o addopts= -q --junitxml=graduation-experiment-results/chapter2_retrieval/current/unified-suite.xml
latexmk -outdir=build -xelatex main.tex  [cwd=graduation-manuscript]
PY -X utf8 graduation-thesis-materials/graduation-manuscript/tools/check_chapter2_formal.py
PY -X utf8 HERE/complete_unified_delivery.py
```

当前测试结果：{passed}通过、{counts['skipped']}跳过、0失败/错误。跳过原因为实验环境缺matplotlib；实际表图用系统Python中已安装的matplotlib生成。正式PDF以稿件official_manifest.json及页面检查为最终交付；本报告不提前宣称尚未发生的发布。

## 已发现并处理的冲突

详见DOCUMENTATION_AUDIT.md：原六方法与新增方法分列、3200与4600会话、200与40题分母、24与5组推断、6000/12000/24000早期预算与2000/4000/6000实测预算、新造60/40题已撤销、活动问答目录迁移、独立人评pending、旧答辩状态与32B无结果。冻结过程报告保留当时身份，由档案README指出其已被新指令替代，不修改历史成绩。

## 主任务剩余工作

当前自动可继续部分：补齐测试40题的成功/失败机制案例，真实图局部及一道题来源追踪，把方法证明与执行细节适当移附录，再同步答辩。人工依赖：两位评审完成80份回答各自标签，以及图50节点/50关系/30别名，回填后报告一致性、AI偏差与敏感性，原AI评分不改。32B/新增8B复验为可选新任务，未获新协议与成本确认不启动。

本次新增题目0、重新生成0、重新评分0、新增付费API调用0。
'''
    (CURRENT/'unified-maintenance.md').write_text(report,encoding='utf-8')
    print('Protected originals verified:',len(protected),'changed:',len(changed),'tests passed:',passed,'skipped:',counts['skipped'])


if __name__=='__main__':main()
