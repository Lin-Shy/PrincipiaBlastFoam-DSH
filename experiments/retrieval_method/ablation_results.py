"""汇总同期完整候选与预注册消融，计算事实家族配对效应和交互项。"""
from __future__ import annotations
import argparse
from collections import defaultdict
from pathlib import Path
import statistics

import leaderboard_audit as audit
import leaderboard_results as quality
from leaderboard_comparison import compatible
from leaderboard_report import number


SINGLES = {
    'role_scope': 'minus_role_scope',
    'conditional_bilateral': 'minus_conditional_bilateral',
    'semantic_recall': 'minus_semantic_recall',
    'paths': 'minus_paths',
    'evidence_groups': 'minus_evidence_groups',
    'gap_strategy': 'minus_gap_strategy',
    'claim_verification': 'minus_claim_verification',
}
INTERACTIONS = {
    'role_scope × conditional_bilateral': ('minus_role_scope','minus_conditional_bilateral',
                                             'minus_role_scope_x_conditional_bilateral'),
    'paths × evidence_groups': ('minus_paths','minus_evidence_groups','minus_paths_x_evidence_groups'),
}


def family_scores(row):
    values=defaultdict(list)
    for session in row['sessions']:
        if session['quality'] is None:
            raise ValueError('unrankable session in ablation analysis')
        values[session['family']].append(int(session['quality']['qa_success']))
    if set(map(len,values.values()))!={6}:
        raise ValueError('expected two paraphrases x three repetitions per family')
    return {family:statistics.mean(scores) for family,scores in values.items()}


def effect(first,second):
    if first.keys()!=second.keys():raise ValueError('family grids differ')
    values=[first[k]-second[k] for k in sorted(first)]
    return {'difference':statistics.mean(values),'paired_family_95ci':quality.interval(values),
            'family_differences':dict(zip(sorted(first),values))}


def analyze(reference,ablations):
    if not reference['all_arms_rankable'] or not ablations['all_arms_rankable']:
        raise ValueError('all source reviews and replay admission are required')
    reference_rows={(r['arm'],r['method']):r for r in reference['arms']}
    full=reference_rows[('full_candidate','retrieval_first')]
    rows={r['arm']:r for r in ablations['arms'] if r['method']=='retrieval_first'}
    if set(rows)!=set(SINGLES.values())|{v[2] for v in INTERACTIONS.values()}:
        raise ValueError('registered ablation arms differ')
    scores={'full_candidate':family_scores(full),**{name:family_scores(row) for name,row in rows.items()}}
    components={name:{'ablated_arm':arm,**effect(scores['full_candidate'],scores[arm])}
                for name,arm in SINGLES.items()}
    interactions={}
    for name,(left,right,both) in INTERACTIONS.items():
        families=sorted(scores['full_candidate'])
        values=[scores['full_candidate'][f]-scores[left][f]-scores[right][f]+scores[both][f] for f in families]
        interactions[name]={'single_ablations':[left,right],'joint_ablation':both,
            'difference_in_differences':statistics.mean(values),'paired_family_95ci':quality.interval(values),
            'family_differences':dict(zip(families,values))}
    operational={r['arm']:{'answers':r['states'].get('reviewed',0),
        'terminal_failures':r['states'].get('tested_terminal_failure',0)} for r in [full,*rows.values()]}
    return {'schema':'candidate-preregistered-ablation-results-v1','reference_arm':'full_candidate/retrieval_first',
        'component_effects_present_minus_removed':components,'interactions':interactions,'operational_counts':operational,
        'interpretation':'Positive component difference means the contemporaneous full candidate exceeded the arm with that component removed. Intervals are pointwise 18-family paired bootstraps; causal interpretation still assumes no unmeasured cohort-time disturbance.',
        'prior_candidate_cohort_used_for_component_effects':False,'holdout_included':False}


def report(result,path):
    lines=['# 完整候选预注册消融结果','',
        '主效应均为同期完整候选减去单组件移除臂。正值表示保留该组件时严格成功率更高；区间按18个事实家族配对重采样。','',
        '| 组件 | 完整候选减去消融 | 95%家族配对区间 |','|---|---:|---:|']
    for name,row in result['component_effects_present_minus_removed'].items():
        ci=row['paired_family_95ci'];lines.append(f"| {name} | {number(row['difference'],True)} | {number(ci[0],True)}–{number(ci[1],True)} |")
    lines+=['','## 预注册交互项','', '| 交互 | 差分之差 | 95%家族配对区间 |','|---|---:|---:|']
    for name,row in result['interactions'].items():
        ci=row['paired_family_95ci'];lines.append(f"| {name} | {number(row['difference_in_differences'],True)} | {number(ci[0],True)}–{number(ci[1],True)} |")
    lines+=['','同期参考和九个消融臂的运行成功/失败数量保存在结果JSON。逐点区间不支持未经校正的全局最优声明；若各臂仍出现不均衡服务故障，组件因果解释相应受限。留出集未参与本表。','']
    path.write_text('\n'.join(lines))


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    for name in ['reference-run','reference-reviews','reference-adjudications','ablation-run','ablation-reviews','ablation-adjudications','output']:
        cli.add_argument('--'+name,type=Path,required=True)
    a=cli.parse_args();out=a.output.resolve();out.mkdir(parents=True,exist_ok=True)
    reference=quality.assemble(a.reference_run.resolve(),a.reference_reviews.resolve(),out/'reference-quality.json',[a.reference_adjudications.resolve()])
    ablations=quality.assemble(a.ablation_run.resolve(),a.ablation_reviews.resolve(),out/'ablation-quality.json',[a.ablation_adjudications.resolve()])
    compatible([a.reference_run.resolve(),a.ablation_run.resolve()],[reference,ablations])
    result=analyze(reference,ablations);audit.save(out/'ablation-effects.json',result);report(result,out/'消融结果.md')
    print('PASS: complete admitted preregistered ablation analysis')


if __name__=='__main__':main()
