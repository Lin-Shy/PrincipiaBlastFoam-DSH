"""开发集描述性配对分析、机制诊断及论文草稿；不改原评分或正文。"""
from collections import defaultdict
import argparse
from common import *

def main(evaluation,output):
    import numpy as np
    source=ARCHIVE/'evaluation'/evaluation
    rows=read(source/'sessions.json');summary=read(source/'summary.json')
    by={(r['method'],r['id'],r['budget']):r for r in rows}
    methods=sorted({r['method'] for r in rows});ids=[q['id'] for q in public_questions()]
    groups=sorted({r['group'] for r in rows});group_of={r['id']:r['group'] for r in rows}
    rng=np.random.default_rng(20261020);draws=rng.integers(0,len(groups),size=(10000,len(groups)))
    comparisons=[]
    for method in methods:
        if method=='graph':continue
        for budget in [2000,4000,6000]:
            delta={q:by[('graph',q,budget)]['evidence_recall']-by[(method,q,budget)]['evidence_recall'] for q in ids}
            sums=np.array([sum(delta[q] for q in ids if group_of[q]==g) for g in groups])
            sizes=np.array([sum(group_of[q]==g for q in ids) for g in groups])
            boot=sums[draws].sum(axis=1)/sizes[draws].sum(axis=1)
            lo,hi=np.quantile(boot,[.025,.975])
            comparisons.append(dict(comparison='graph - '+method,budget=budget,difference_points=100*sum(delta.values())/200,
                exploratory_cluster_bootstrap95_lower=100*float(lo),exploratory_cluster_bootstrap95_upper=100*float(hi),
                groups=24,repeats=10000,seed=20261020,confirmatory=False))
    run=ARCHIVE/'runs'/summary['run_id'];mechanisms=[]
    from principia_core.retrieval.knowledge_qa import FrozenKnowledgeCorpus
    from functools import lru_cache
    corpus=FrozenKnowledgeCorpus(RESOURCES/'corpus',RESOURCES/'corpus-manifest.json')
    corpus.lines=lru_cache(maxsize=None)(corpus.lines)
    import json
    deliveries={(r['id'],r['budget']):r for r in (json.loads(line) for line in (run/'graph/deliveries.jsonl').read_text(encoding='utf-8').splitlines())}
    for q in ids:
        t=read(run/'graph/traces'/(q+'.json'))
        anchors=set()
        for slot in t['full_slots']:
            native=next(r for r in t['ranking']['items'] if r['node_id']==slot['node_id'])
            for e in native['anchors']:anchors|={(e['path'],n) for n in range(e['start'],e['end']+1)}
        for budget in [2000,4000,6000]:
            # Read only this question's actual response from its immutable ledger.
            original=deliveries[(q,budget)]
            delivered={(r['path'],r['line']) for r in original['delivered_lines']}
            extra=delivered-anchors
            mechanisms.append(dict(id=q,budget=budget,delivered_anchor_lines=len(delivered&anchors),
                delivered_supplement_lines=len(extra),supplement_characters=sum(len(corpus.lines(p)[n-1]) for p,n in extra),
                full_recall=by[('graph',q,budget)]['evidence_recall'],anchor_recall=by[('anchor_only',q,budget)]['evidence_recall']))
    out=ARCHIVE/'reports'/output
    save(out/'paired_retrieval.json',dict(source_sha256=sha(source/'summary.json'),comparisons=comparisons,
        mechanism_delivery=mechanisms,analysis_sha256=sha(Path(__file__)),
        boundary='Exploratory descriptive uncertainty on exposed bank; analysis added after initial retrieval results. No confirmatory p-value or robustness claim.'))
    overall=[r for r in summary['overall'] if r['budget']==6000]
    lines=['# 本轮实际结果与论文修订草稿','','## 已完成','',
        f"固定查询{len(methods)}方法×200题×3预算，共{len(rows)}份实际交付。全部分母保留；实际JSON字符包络计入预算；未调用付费生成或裁判。",'',
        '|方法|登记证据完整召回|整题证据齐全|部分证据行覆盖|平均实返字符|', '|---|---:|---:|---:|---:|']
    for r in overall:lines.append(f"|{r['method']}|{100*r['evidence_recall']:.2f}%|{100*r['all_evidence']:.2f}%|{100*r['partial_evidence_overlap']:.2f}%|{r['response_characters']:.1f}|")
    lines+=['','## 机制观察（全部为开发集检索）','']
    for b in [2000,4000,6000]:
        r=[r for r in mechanisms if r['budget']==b]
        wins=sum(x['anchor_recall']>x['full_recall'] for x in r);losses=sum(x['anchor_recall']<x['full_recall'] for x in r)
        lines += [f'- {b}字符：仅锚点召回高于完整图{wins}题，低于完整图{losses}题；完整图平均交付补充正文{sum(x["supplement_characters"] for x in r)/200:.1f}字符（不含JSON包络）。']
    lines+=['','A1全200题初始扫描种子一致、扩展边为0；A2全200题候选排序与完整图一致且无槽位回填，核验见audit/graph_trace_invariants.json。',
        '差异可能受原文单元粒度、字段/别名扫描、排序和有限预算共同影响；不能把完整召回解释为语义支持、正确回答或物理有效性。',
        '配对24知识组bootstrap范围保存在paired_retrieval.json，属于看到初步数据后追加的描述性分析；不作确认性显著性断言。','',
        '## 尚未开始与阻断','',
        '- 新14B回答、匿名AI评分、端到端EAS及正式检验：待用户授权；旧回答保持历史身份。',
        '- 人工裁判一致性、AI人工差值与图正确率：等待独立人工填写，均pending。',
        '- 60题新留出：只有流程模板，未创建事实题、未冻结、未运行检索或QA。','',
        '## 建议正文调整（尚未写入稿件）','',
        '2.2：保留来源归属、节点锚点、真实局部图及原文回读；把遍历/预算不变量证明压入附录。完整图不重新选择。',
        '2.3：将父内容与相邻补充统一描述为上下文交付机制；A2同时缩至节点锚点，其差异不能单独归因父内容。B3是独立原文解析，不等同图来源单元。',
        '2.4：新增固定自然问题检索小节，列三档实际JSON字符预算、公共去重及BGE-M3 Dense（CLS/L2，CPU float32，官方revision）与BM25同分段；与Agent自主查询明确分开。',
        '2.5：先给真实检索曲线，正式QA表只填已实际生成评分的方法；新组EAS标记未运行。按主结果、类型差异、消融、取证/生成错位、失败/成本组织。',
        '2.6：披露旧200题暴露、完整图和指标事后调整、原8B复用/基础搜索后补、本轮开发性选择及同系列裁判局限。新留出通过真实人审和全部冻结后才启动。','',
        '## 可直接改写的结果段落草稿','',
        '在已暴露的200题专业知识问答集上，本轮保持自然问题不变，以固定实际序列化交付预算评价检索覆盖。登记证据完整召回按实际送达原文行的并集判断，部分行重叠另报。该实验不含生成Agent，不能替代端到端有效回答得分；已有历史回答只用于带批次标识的失败案例分析。',
        '完整数值和对应run ID来自evaluation/'+evaluation+'；正式论文图表应在新QA确认后另行加入稿件assets，原正文与历史分数未修改。']
    (out/'thesis_revision_notes.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    table=['% Generated from '+evaluation+'; fixed-query retrieval ONLY, no QA EAS.',r'\begin{tabular}{lrrr}',r'\hline',r'Method & Evidence recall (\%) & Complete set (\%) & Mean chars \\',r'\hline']
    for r in overall:table.append(r['method'].replace('_',r'\_')+f" & {100*r['evidence_recall']:.2f} & {100*r['all_evidence']:.2f} & {r['response_characters']:.1f} \\\\")
    table += [r'\hline',r'\end{tabular}']
    (out/'retrieval_table_draft.tex').write_text('\n'.join(table)+'\n',encoding='utf-8')
    print('descriptive paired retrieval analysis and thesis draft saved',len(rows))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--evaluation',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();main(a.evaluation,a.output)
