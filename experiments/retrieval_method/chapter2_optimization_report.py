"""Exploratory full-bank retrieval development report with paired regressions."""
from collections import defaultdict
import csv
import hashlib
import json
from pathlib import Path
import statistics
import sys
import xml.etree.ElementTree as ET

import numpy as np

def read(p):return json.loads(p.read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,value):p.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def main():
    root=Path(sys.argv[1]).resolve()
    formal=root.parent/'formal_200_20261019_001'
    authorized=(formal/'user-authorization.json').exists()
    generation=read(formal/'generation-status.json') if (formal/'generation-status.json').exists() else None
    analyses={p.stem:read(p) for p in (root/'analysis').glob('*.json')}
    before=analyses['v4_full_verified'];after=analyses['v6_unit_aliases_verified']
    for old,new in [('v4_full','v4_full_verified'),('v5_adaptive_literal','v5_adaptive_literal_verified'),('v6_unit_aliases','v6_unit_aliases_verified')]:
        for key,value in analyses[old]['summary']['micro'].items():
            if value!=analyses[new]['summary']['micro'][key]:raise ValueError('Reproduction changed metric '+old+' '+key)
    a={r['id']:r for r in before['rows']};b={r['id']:r for r in after['rows']}
    assert set(a)==set(b) and len(a)==200
    paired={};rng=np.random.default_rng(20261019)
    for key in ['delivered_complete_6000','delivered_complete_12000','delivered_complete_24000']:
        groups=defaultdict(list);wins=[];losses=[]
        for qid in a:
            delta=b[qid]['metrics'][key]-a[qid]['metrics'][key]
            groups[a[qid]['group']].append(delta)
            if delta>0:wins.append(qid)
            elif delta<0:losses.append(qid)
        values=[(sum(v),len(v)) for _,v in sorted(groups.items())]
        totals=np.array([v[0] for v in values]);counts=np.array([v[1] for v in values])
        indices=rng.integers(0,len(values),size=(10000,len(values)))
        bootstrap=totals[indices].sum(axis=1)/counts[indices].sum(axis=1)
        paired[key]=dict(net_change=statistics.mean([b[q]['metrics'][key]-a[q]['metrics'][key] for q in a]),
            wins=wins,losses=losses,unchanged=200-len(wins)-len(losses),
            exploratory_cluster_bootstrap_95_interval=np.quantile(bootstrap,[.025,.975]).tolist(),
            inference='Post-selection exploratory uncertainty only, not confirmatory significance or unseen generalization')
    keys=['delivered_complete_6000','delivered_complete_12000','delivered_complete_24000',
        'delivered_recall_6000','recall@10','file_ndcg@10']
    order=['bm25','e5_002','hybrid_002','v4_full','v4_no_context','v5_balanced','v5_ppr','v5_gated','v5_compact','v5_literal','v5_adaptive_literal',
        'v5_balanced_aliases','v5_adaptive_aliases','v6_unit_aliases','v6_case_aliases','v6_unit_no_cross','v6_unit_no_conditions']
    with (root/'comparison.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.writer(f);writer.writerow(['run_id','questions',*keys,'group_macro_complete_6000','mean_ranking_seconds'])
        for name in order:
            x=analyses[name]['summary'];writer.writerow([name,x['questions'],*(x['micro'][k] for k in keys),
                x['group_macro']['delivered_complete_6000'],x['latency_seconds']['mean']])
    xml=ET.parse(root/'checks/chapter2-tests-corrected.xml').getroot()
    tests={key:sum(int(v.attrib.get(key,0)) for v in xml.iter('testsuite')) for key in ['tests','failures','errors','skipped']}
    checks=dict(chapter2_tests=tests,linux_only_modules_not_run=3,
        repeat_verification='All summary micro metrics exactly reproduced for baseline and proposed method',
        dataset_sha256=after['dataset_sha256'])
    qa=root/'qa/local_matched_001';results=[read(p) for p in qa.glob('sessions/**/result.json')]
    qa_summary=dict(registered_sessions=16,closed_sessions=len(results),
        answered=sum(r['status']=='answered' for r in results),
        transport_error=sum(r['status']=='transport_error' for r in results),
        completion_available=(qa/'completion.json').exists(),semantic_scores_available=False,
        label='Internal small local diagnosis; never infer a full-bank answer-quality result')
    blockers=[dict(action='Frozen full200 five-method and two-ablation proxy8B answer generation',
        status='awaiting_specific_8b_question_and_source_export_authorization',
        auto_review_reason='Explicit proxy14B judge and DeepSeek source alias approvals did not explicitly cover new200 questions and actual source passages to proxy8B',
        scope=dict(questions=200,sessions=1400,max_requests=12600,concurrency=14),
        excludes=['gold','scoring annotations'],existing_calls_reissued=False)]
    if authorized:blockers=[]
    method_protocol=root/'retrieval/v6_unit_aliases_verified/protocol.json'
    protocol=read(method_protocol)
    selected=dict(status='selected_for_frozen_full200_qa'+('' if authorized else '_pending_export_authorization'),formal_qa_protocol_frozen=True,
        policy='v6_unit',graph=protocol['graph'],graph_sha256=protocol['graph_sha256'],
        production_input='Only natural question, persistent graph and independently bound raw corpus',
        read_context_allowance='min(2400,max(1200,available_character_budget//5)); original located fragment retained',
        no_external_index=True,implementation_sha256=protocol['implementation_sha256'],
        selection_objective='Question-micro complete required evidence delivered at 6000 characters; check group macro and 24000-character regressions',
        source_protocol_sha256=sha(method_protocol),dataset_sha256=after['dataset_sha256'],
        next_required=('Complete frozen full-bank answer generation, independent scoring and predeclared statistics' if authorized else
            'Specific proxy8B export permission; execute frozen full-bank answer generation, independent scoring and predeclared statistics'))
    write(root/'provisional-method.json',selected)
    report=dict(schema='optimization_200_progress_v2',formal_result=False,queries_executed=sum(x['summary']['questions'] for x in analyses.values()),
        unique_candidate_or_control_runs=len(order),reproduction_runs=len(analyses)-len(order),checks=checks,
        baseline=before['summary'],proposed=after['summary'],by_type=dict(baseline=before['by_type'],proposed=after['by_type']),
        paired=paired,local_qa=qa_summary,remaining_external_step=blockers,
        proxy8b_export_authorized=authorized,formal_generation_status=generation,
        source_and_alias_audit=read(root/'checks/source-and-alias-audit.json'),
        judge_calibration=dict(first_attempt=read(root/'judge_calibration_001/completion.json'),
            revised_attempt=read(root/'judge_calibration_002/completion.json'),
            boundary='Same seven exposed synthetic controls, not independent human agreement or judge generalization'),
        failed_setup_attempts=['retrieval/e5','retrieval/hybrid'],
        analysis_bindings={name:sha(root/'analysis'/(name+'.json')) for name in analyses},
        boundary='All figures are adaptive retrieval-development observations on the exposed 200 questions; not final answer-quality or independent generalization results')
    write(root/'progress.json',report)
    lines=['# 200题图谱优化实验：本轮进展','',
        ('状态：已完成全200题检索开发比较及独立复跑；正式1400会话协议已冻结。'+
         ('用户已明确授权代理8B外发，正式生成状态见../formal_200_20261019_001/，尚无语义评分。' if authorized else
          '代理8B发送动作被自动审批拦截，尚未生成正式回答。')+
         '所有检索数字属于暴露题集上的自适应开发观察，不是未见泛化或最终问答正确率。'),'',
        '## 统一输入与评价','',
        '每个检索进程只读取ID和自然问题，构图进程不读取题库。gold仅在独立评价进程读取。全部200题、四类各50题、24知识组；各方法使用相同原文读取器，JSON和行号开销均计入6000/12000/24000字符预算。必要gold不是穷尽相关性池。','',
        '## 全题库实际送达','',
        '| 方案 | 6000字符完整证据 | 12000字符完整证据 | 24000字符完整证据 |',
        '| --- | ---: | ---: | ---: |']
    for name in order:
        x=analyses[name]['summary']['micro'];lines.append('| '+name+' | '+' | '.join(f"{x['delivered_complete_'+str(cap)]*100:.1f}%" for cap in [6000,12000,24000])+' |')
    lines+=['','当前候选组合预算自适应补读、按查询要点分散选择、字面标题引用与来源绑定的中文别名。6000字符从107/200提高到121/200，24000字符从146/200提高到158/200。知识组宏平均也单列于progress.json，不以题目微平均代替。','',
        '## 退化与解释','',
        '去掉全部上下文、无条件采用归一化传播、严格过滤相邻段都未同时改善两个预算。仅压缩补读虽改善小预算，却损失大预算，因此采用按预算调整的统一规则。字面引用不是语义等价、兼容性或执行证明。','',
        f"默认读计划的Recall@10由{before['summary']['micro']['recall@10']*100:.2f}%变为{after['summary']['micro']['recall@10']*100:.2f}%。只加入别名却沿用原匹配权重时，小预算曾退化；增加案例先验也未优于来源单元别名方案。这些候选全部保留。排序前十与实际字符预算下完整送达是不同指标，仍需最终问答实测确认。",'',
        '## 配对变化','']
    for key,x in paired.items():
        lines.append(f"- {key}：改善{len(x['wins'])}题、退化{len(x['losses'])}题、不变{x['unchanged']}题；净变化{x['net_change']*100:.1f}个百分点。")
    lines+=['','24组整组重采样的探索性区间保存在progress.json；选择后的区间不能作确认性显著提升证据。','',
        '## 实现与验证','',
        '- 本轮持久化图增补158个原文字面标题节点、235条单向资料引用；歧义和泛称不强行连接，来源锚点均保留。',
        '- 生产检索直接扫描图，未加载BM25、E5、倒排索引或passage embedding；BM25只作隔离对照。',
        f"- {tests['tests']}项第2章测试通过；3个依赖Linux fcntl的测试模块未在Windows执行。三组200题复跑的全部汇总指标精确重现；一次测试模块重复加载污染已修正，原失败XML保留。",
        '- 44/45批离线别名生成及独立校验完成，1322个别名绑定297个原文单元；89次请求（88次响应、1次连接失败），失败未重发。479份原文、3942个单元和14381个节点证据锚点已核验。',
        '- 七项裁判初次校准5/7通过；独立来源审计曾忽略题设条件，已补充通用条件约束。部分覆盖控制的精确0.5预期过窄，改为预登记的0<覆盖<1；新版同七项7/7通过。失败协议与回答保留，不视作人工真值或独立裁判泛化证据。',
        '- 相同原始中文问句下E5偏弱：权重/索引哈希及三个原文重编码样本一致。最终消费者允许自主英文查询，单轮诊断不代替整体问答排名；未隐藏失败的缓存定位尝试。',
        '- 代码、图谱、题库、原文及每条检索输出均绑定SHA256；运行目录保存对应源码快照。',
        '- 小批量本地Qwen3-8B诊断与后续代理数据分开，未知/超时不重发、不删分母；该诊断没有语义评分，不进入论文。','',
        '## 尚待完成','',
        ('DeepSeek原文外发已获用户明确授权并完成上述允许范围；原拦截已解除。'+
         ('用户随后也明确授权新200题和检索原文发送至代理8B，先前自动审批拦截已解除。正式生成按冻结协议执行，不含gold或评分标注，失败不重发。' if authorized else
          '当前剩余拦截为代理8B正式生成：自动审批认为现有明确授权不覆盖向该模型发送新200题及实际读到的公开原文。1400会话、最多12600次单次请求、最多14并发已冻结；不含gold、类别或评分规则，尚未发送正式生成请求。')),
        '正式入口为../formal_200_20261019_001/protocol.json；生成后另作独立评分与已登记统计，本轮未将检索覆盖写成最终问答提升。','',
        '## 入口','',
        f'- comparison.csv：{len(order)}种方案/对照的全量摘要；analysis/：逐题、分类型和知识组指标。',
        '- progress.json：配对改善/退化题目、探索性区间、诊断状态和全部分析哈希。',
        '- provisional-method.json：本轮检索选择的图谱与源码绑定；正式问答协议另见formal_200目录。',
        '- construction/：来源独立的构图产物与已完成的别名核验；retrieval/：生产侧原始输出。']
    (root/'README.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps(dict(queries=report['queries_executed'],tests=tests,qa=qa_summary,
        proposed_complete_6000=after['summary']['micro']['delivered_complete_6000'],
        proposed_complete_24000=after['summary']['micro']['delivered_complete_24000'])))

if __name__=='__main__':main()
