"""Remove residual live status conflicts discovered by the documentation scan."""
from common import *
import re


def main():
    changes=[]
    paths=[WORKSPACE/'graduation-datasets/README.md',
        WORKSPACE/'graduation-thesis-materials/graduation-research/OVERVIEW.md',
        WORKSPACE/'graduation-thesis-materials/graduation-research/action-plans/chapter01.md',
        WORKSPACE/'graduation-thesis-materials/graduation-research/chapters/chapter01.md',
        WORKSPACE/'graduation-thesis-materials/graduation-research/chapters/chapter05.md',
        WORKSPACE/'graduation-thesis-materials/graduation-visualization/README.md',
        WORKSPACE/'graduation-thesis-materials/graduation-visualization/chapter_02_knowledge_graph_retrieval/README.md']
    for path in paths:
        text=path.read_text(encoding='utf-8');before=sha(path)
        text=text.replace('8B、14B均完成六方法与两项消融，每模型1600、合计3200比较会话；',
            '当前九方法与四项消融统一呈现，共4600既有会话，E5/BGE与两次核心参照均保留；')
        text=text.replace('第2章8B、14B全200题六方法及两项消融已完成，',
            '第2章九方法/四消融、160题开发与40题测试统一结果已更新，')
        text=text.replace('正文与摘要已同步第2章8B/14B六方法结果；',
            '正文与摘要已同步第2章九方法/四消融统一结果，保留E5和BGE；')
        text=text.replace('8B/14B六方法及两消融已完成，32B待API；',
            '九方法/四消融统一管理、4600既有会话，开发160/测试40；32B无结果；')
        text=text.replace('第2章只维护唯一200题活动版本及可复建来源；',
            '第2章活动题集为两个实体目录development_v1_160与test_v1_40，原200题保留为来源；')
        text=text.replace('使用build_split_results.py从原逐题评分的固定ID子集生成assets/chapter2/dev160_test40/。',
            '使用build_unified_results.py从current统一模型/分集统计生成assets/chapter2/dev160_test40/，同时纳入E5与BGE及两次核心参照。')
        text=text.replace('当前正文为200题、8B/14B六方法及两项消融，合计3200比较会话。',
            '当前正文以160题开发/40题测试、九方法与四消融为范围，合计4600既有会话。')
        text=text.replace('：当前正式结果表图入口。两份输入位于',
            '：原全200题批次的历史重建入口，不再生成当前40题论文结果。两份输入位于')
        text=text.replace('已完成200题8B/14B六方法及两项消融表图与可编辑方法图；当前结果由build_model_scale_results.py生成，',
            '已完成九方法/四消融统一表图、固定查询预算曲线与可编辑方法图；当前结果由build_unified_results.py生成，')
        text=text.replace('更新时间：2026-10-19。','更新时间：2026-10-20。')
        path.write_text(text,encoding='utf-8')
        changes.append(dict(path=path.relative_to(WORKSPACE).as_posix(),before_sha256=before,after_sha256=sha(path)))
    # Replace dangerous superseded plotting entry points with a single delegate.
    visual=WORKSPACE/'graduation-thesis-materials/graduation-visualization/chapter_02_knowledge_graph_retrieval'
    for name in ['build_split_results.py','build_round2_split_results.py']:
        path=visual/name;before=sha(path)
        path.write_text('"""Compatibility entry: all current methods are published together."""\nfrom build_unified_results import main\n\nif __name__ == "__main__":\n    main()\n',encoding='utf-8')
        changes.append(dict(path=path.relative_to(WORKSPACE).as_posix(),before_sha256=before,after_sha256=sha(path)))
    # Fix English number/word spacing before compilation, preserving numeric values.
    p=WORKSPACE/'graduation-thesis-materials/graduation-manuscript/docs/abstract.tex';text=p.read_text(encoding='utf-8');before=sha(p)
    text=re.sub(r'\bscores(?=\d)','scores ',text);p.write_text(text,encoding='utf-8')
    changes.append(dict(path=p.relative_to(WORKSPACE).as_posix(),before_sha256=before,after_sha256=sha(p)))
    audit_path=CURRENT/'documentation-maintenance.json';audit=read(audit_path)
    audit['changes'].extend(changes)
    audit_path.write_text(json.dumps(audit,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('Reconciled remaining live status statements and delegated old plot entry points')


if __name__=='__main__':main()
