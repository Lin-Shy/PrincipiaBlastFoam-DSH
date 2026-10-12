"""重算来源评审后合并兼容开发评测，生成跨运行的严格成功率配对比较。"""
from __future__ import annotations
import argparse
from collections import defaultdict,Counter
from fractions import Fraction
from pathlib import Path
import statistics
import leaderboard_audit as audit
import leaderboard_results as quality
from leaderboard_report import LABELS,POLICIES,number


def compatible(roots,reports):
    identities=[]
    for root,report in zip(roots,reports):
        protocol=audit.verify(root)
        if report['protocol_sha256']!=audit.sha(root/'protocol.json') or not report['all_arms_rankable']:
            raise ValueError('incomplete or unbound quality cohort')
        identity={'corpus':protocol['corpus_id'],'model':protocol['model'],'replicates':protocol['replicates'],
                  'provider_fingerprints':sorted(report['provider_fingerprints'])}
        anchor=next(iter(protocol.get('groups', {'control': []})))
        for name in ['questions.json','evaluation_only/annotations.json','evaluation_only/scoring-rules.json']:
            identity[name]=audit.sha(root/anchor/name)
        identities.append(identity)
    if not identities:raise ValueError('no cohorts')
    for identity in identities[1:]:
        differences=[k for k in identities[0] if identities[0][k]!=identity[k]]
        if differences:raise ValueError('incompatible cohorts: '+', '.join(differences))
    return identities[0]


def exact_success(row):
    categories=defaultdict(list)
    for session in row['sessions']:categories[session['category']].append(bool(session['quality']['qa_success']))
    return sum((Fraction(sum(values),len(values)) for values in categories.values()),Fraction())/len(categories)


def combine(roots,reports,names):
    identity=compatible(roots,reports);arms=[];families={};family_categories={}
    for name,report in zip(names,reports):
        for row in report['arms']:
            key=(name,row['arm'],row['method']);values=defaultdict(list);categories={}
            for s in row['sessions']:
                values[s['family']].append(int(s['quality']['qa_success']));categories[s['family']]=s['category']
            if len(set(map(len,values.values())))!=1:raise ValueError('family grids unequal')
            if family_categories and family_categories!=categories:raise ValueError('fact family identity mismatch')
            family_categories=categories
            families[key]={f:statistics.mean(v) for f,v in values.items()}
            exact=exact_success(row)
            arms.append({**{k:v for k,v in row.items() if k!='sessions'},'cohort':name,'exact_success_fraction':str(exact)})
    # The frozen baseline bootstrap samples balanced fact families as whole units.
    if len(set(Counter(family_categories.values()).values()))!=1:raise ValueError('unbalanced family categories require a preregistered stratified estimator')
    ranked=sorted(arms,key=lambda row:(-Fraction(row['exact_success_fraction']),row['cohort'],row['arm'],row['method']))
    previous=None;rank=0
    for index,row in enumerate(ranked,1):
        score=Fraction(row['exact_success_fraction'])
        if score!=previous:rank=index;previous=score
        row['rank']=rank
    pairs=[];keys=list(families)
    for i,first in enumerate(keys):
        for second in keys[i+1:]:
            diffs=[families[first][f]-families[second][f] for f in sorted(family_categories)]
            pairs.append({'first':list(first),'second':list(second),'difference':statistics.mean(diffs),
                          'paired_family_95ci':quality.interval(diffs)})
    return {'schema':'compatible-development-leaderboard-v1','identity':identity,'arms':ranked,'paired_comparisons':pairs,
            'comparison_scope':'Whole systems under matching inputs, model and total budgets. Candidate has six exploration decisions plus planning and checking; original arms have eight exploration decisions. Component attribution requires ablations.',
            'uncertainty':'Pointwise paired 18-family bootstrap intervals, not simultaneous multiple-comparison intervals; same-model-family source judges, not independent-human validation.',
            'holdout_included':False}


def write_report(result,output):
    lines=['# 基线与完整候选统一开发总榜','',
        '全部输入队列重新通过原始来源评审和回放准入后合并。未使用旧QA成绩，未将留出集混入开发集。','',
        '| 排名 | 配置 | 运行结果 | 严格成功率 | 家族95%区间 | 答案要点 | 引用支持 | 跨源完整性 |',
        '|---:|---|---:|---:|---:|---:|---:|---:|']
    for row in result['arms']:
        label=LABELS.get(row['arm'],row['arm'])+'·'+POLICIES.get(row['method'],row['method']);ci=row['strict_success_95ci'];m=row['metrics']
        metrics=[m[k]['macro_over_applicable_categories'] for k in ['answer_accuracy','citation_accuracy']]
        cross=m['cross_source_completeness']['by_category']['cross']['mean']
        states=row['states'];run_state=str(states.get('reviewed',0))+'答案/'+str(states.get('tested_terminal_failure',0))+'运行失败'
        lines.append('| '+' | '.join([str(row['rank']),label,run_state,number(float(Fraction(row['exact_success_fraction'])),True),
             number(ci[0],True)+'–'+number(ci[1],True),*[number(v) for v in metrics],number(cross)])+' |')
    lines+=['','## 完整候选的配对差值','',
            '以下为完整候选减去各对照的严格成功率差值。区间按整个事实家族配对重采样；属于逐对区间，不作多重比较后的全局最优声明。','',
            '| 对照 | 候选减对照 | 95%家族配对区间 |','|---|---:|---:|']
    for p in result['paired_comparisons']:
        a,b=p['first'],p['second']
        if (a[1]=='full_candidate')==(b[1]=='full_candidate'):continue
        sign=1 if a[1]=='full_candidate' else -1;other=b if sign==1 else a
        ci=p['paired_family_95ci'];ci=ci if sign==1 else [-ci[1],-ci[0]]
        label=LABELS.get(other[1],other[1])+'·'+POLICIES.get(other[2],other[2])
        lines.append(f"| {label} | {number(sign*p['difference'],True)} | {number(ci[0],True)}–{number(ci[1],True)} |")
    failed=sum(row['states'].get('tested_terminal_failure',0) for row in result['arms'])
    lines+=['',f'严格成功率把冻结重试策略耗尽的 {failed} 个会话计为运行失败。答案要点、引用支持和跨源完整性只在实际生成并完成来源评审的答案上适用，不能解释为全队列内容质量。',
            '本表比较整体系统。强无图与完整候选共享混合召回、缺口策略及主张核验；原八配置采用不同探索/核验分配但相同总预算。实际组件收益仍以消融为准。来源评审与作答使用同模型家族；开发集结果不替代冻结后的留出检验。完整费用与逐会话证据见各队列质量JSON和费用总账。','']
    output.write_text('\n'.join(lines))


def main():
    cli=argparse.ArgumentParser(description=__doc__);cli.add_argument('--config',type=Path,required=True);cli.add_argument('--output',type=Path,required=True);a=cli.parse_args()
    config=audit.read(a.config);out=a.output.resolve();out.mkdir(parents=True,exist_ok=True)
    roots=[];reports=[];names=[];bindings=[]
    for cohort in config['cohorts']:
        root=Path(cohort['run']);target=out/(cohort['name']+'-quality.json')
        report=quality.assemble(root,Path(cohort['reviews']),target,[Path(p) for p in cohort.get('adjudications',[])])
        roots.append(root);reports.append(report);names.append(cohort['name']);bindings.append({'name':cohort['name'],'quality_sha256':audit.sha(target)})
    result=combine(roots,reports,names);result['source_cohorts']=bindings
    audit.save(out/'combined-quality.json',result);write_report(result,out/'统一开发总榜.md')
    print('PASS: combined complete compatible development cohorts')


if __name__=='__main__':main()
