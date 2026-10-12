"""从通过准入的统一榜单导出中文报告；未完整评审的结果不展示质量排名。"""
from __future__ import annotations
import argparse
from collections import Counter
from pathlib import Path
import leaderboard_audit as audit
from leaderboard_cost import stage

LABELS={'control':'公共文本无图','native':'Graphify原生','text_adapter':'Graphify文本适配','GN':'GN','GH':'GH',
        'GH_evidence':'GH＋条件跨源证据搜索','strong_no_graph':'强无图混合检索','full_candidate':'完整候选'}
POLICIES={'no_graph':'无图','graph_optional':'可选图','graph_first':'优先图','retrieval_first':'优先检索'}


def number(value,percent=False):
    if value is None:return '未测/不适用'
    return f'{100*value:.2f}%' if percent else f'{value:.4f}'


def metric(row,key,category=None):
    values=row['metrics'].get(key,{})
    return values.get('by_category',{}).get(category,{}).get('mean') if category else values.get('macro_over_applicable_categories')


def render(quality_path,run,prices,output):
    report=audit.read(quality_path);protocol=audit.verify(run)
    if report['protocol_sha256']!=audit.sha(run/'protocol.json'):raise ValueError('report/run identity mismatch')
    if not report['all_arms_rankable'] or not report.get('replay_and_budget_admission',{}).get('passed'):
        raise ValueError('do not publish rankings before complete source review and replay')
    # Keep the published report bound to every response, result and successful replay receipt.
    for relative,h in report['replay_and_budget_admission']['files'].items():
        if audit.sha(run/relative)!=h:raise ValueError('report admission evidence changed')
    questions=audit.read(run/'control/questions.json');families=len({q['item_id'] for q in questions})
    lines=['# 开发集统一评测报告','',
           '本报告仅使用当前冻结协议下的新问答和来源评审，不并入旧QA分数。全部配置通过完整网格、来源评审、模型身份、预算和零模型回放准入。','',
           f"语料身份：`{protocol['corpus_id']}`。模型：`{protocol['model']}`；供应商指纹：`{next(iter(report['provider_fingerprints']))}`。每配置{len(questions)}输入、{families}事实家族、{protocol['replicates']}重复，共{len(questions)*protocol['replicates']}会话。留出集另行评测，不混入开发集。",'',
           '## 答案质量与证据','',
           '| 配置 | 三类等权严格成功率 | 95%家族区间 | 答案要点 | 引用支持 | 跨源类完整性 | 两改写均成功 |',
           '|---|---:|---:|---:|---:|---:|---:|']
    for row in sorted(report['arms'],key=lambda r:-r['strict_success_macro']):
        label=LABELS.get(row['arm'],row['arm'])+'·'+POLICIES.get(row['method'],row['method']);ci=row['strict_success_95ci']
        lines.append('| '+' | '.join([label,number(row['strict_success_macro'],True),f'{number(ci[0],True)}–{number(ci[1],True)}',
           number(metric(row,'answer_accuracy')),number(metric(row,'citation_accuracy')),number(metric(row,'cross_source_completeness','cross')),
           number(row['both_paraphrases_success_rate'],True)])+' |')
    lines+=['','## 路径、条件与作用域','',
            '| 配置 | 案例准确性 | 文件/字典准确性 | 证据状态 | 歧义消解 | 必需证据召回 |',
            '|---|---:|---:|---:|---:|---:|']
    for row in report['arms']:
        label=LABELS.get(row['arm'],row['arm'])+'·'+POLICIES.get(row['method'],row['method'])
        lines.append('| '+' | '.join([label,*[number(metric(row,k)) for k in ['case_accuracy','file_dictionary_accuracy','evidence_status_accuracy','ambiguity_accuracy','required_evidence_recall']]])+' |')
    lines+=['','## 调用与费用','',
            '表中的美元范围只重建已报告用量，不是账户账单。未知尝试未计为零；跨峰谷计费边界保留区间。构建、审阅和仲裁费用在费用总账中另列。公开费率来源：[DeepSeek官方价格表]('+prices['source_url']+')。','',
            '| 配置 | 已报告token | 未知用量尝试 | 会话延迟p50/p95（秒） |',
            '|---|---:|---:|---:|']
    for row in report['arms']:
        cost=Counter();unknown=0;latency=[]
        for session in row['sessions']:
            c=session['cost'];cost.update(c['reported_usage']);unknown+=c['unknown_usage_attempts']
            if c['session_seconds'] is not None:latency.append(c['session_seconds'])
        label=LABELS.get(row['arm'],row['arm'])+'·'+POLICIES.get(row['method'],row['method'])
        times=f"{number(audit.percentile(latency,.5))}/{number(audit.percentile(latency,.95))}"
        lines.append(f"| {label} | {cost.get('total_tokens','未知')} | {unknown} | {times} |")
    lines+=['','各图构建臂的问答已报告费用（同臂的首步策略合计）：','']
    for group in protocol['groups']:
        amount=stage(run/group,prices)['reported_usage_usd_interval']
        lines.append(f"- {LABELS.get(group,group)}："+(f"${amount[0]:.4f}–${amount[1]:.4f}。" if amount else '未取得可计价用量。'))
    lines+=['','## 配对比较','',
            '差值为前者减后者；以18个事实家族配对重采样，改写与重复保留在家族内部。区间跨零时不据点估计声称稳定优势。','',
            '| 前者 | 后者 | 严格成功率差值 | 95%配对家族区间 |','|---|---|---:|---:|']
    for pair in report['paired_comparisons']:
        ci=pair['paired_family_95ci']
        lines.append(f"| {'/'.join(pair['first'])} | {'/'.join(pair['second'])} | {number(pair['difference'],True)} | {number(ci[0],True)}–{number(ci[1],True)} |")
    lines+=['','来源评审与作答模型属于同一家族。方法盲化与原文核验不等同独立人工或模型多样性验证。开发集已被观察，本报告不证明留出泛化。完整候选与强无图共享混合召回和问答核验；与原八配置的主榜比较属于整体系统对比，组件贡献须以预登记消融检验。','',
            f"冻结协议SHA：`{report['protocol_sha256']}`；质量报告SHA：`{audit.sha(quality_path)}`。完整逐会话、维度适用数、原响应绑定及回放证据均在对应质量JSON中保留。",'']
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text('\n'.join(lines))


if __name__=='__main__':
    cli=argparse.ArgumentParser(description=__doc__)
    for name in ['quality','run','prices','output']:cli.add_argument('--'+name,type=Path,required=True)
    a=cli.parse_args();render(a.quality,a.run.resolve(),audit.read(a.prices),a.output)
    print('published complete-grid development report')
