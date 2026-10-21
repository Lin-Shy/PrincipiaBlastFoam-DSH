"""Publication drafts from closed new QA results; never mutate historical assets."""
import argparse
from collections import Counter
import csv
import statistics
from common import *

GEN=ARCHIVE/'e2e_runs/answer14b_003'
LABELS=dict(graph='Source graph',bm25='BM25',bge_m3='BGE-M3 Dense',bm25_bge_m3='BM25 + BGE-M3',bm25_parent='BM25 + parent',no_traversal='No traversal',anchor_only='Anchors only')
MAIN=['graph','bm25','bge_m3','bm25_bge_m3','bm25_parent']
ABS=['graph','no_traversal','anchor_only']

def interval(v,stem='score'):
    return f"[{100*v[stem+'_lower']:.2f}, {100*v[stem+'_upper']:.2f}]"

def write_csv(path,rows):
    with path.open('x',encoding='utf-8-sig',newline='')as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)

def receipt_usage(paths):
    totals=Counter();statuses=Counter();unknown=0;bindings={}
    for path in paths:
        r=read(path);usage=r.get('response',{}).get('usage',{});statuses[r['status']]+=1
        for k in ['prompt_tokens','completion_tokens','total_tokens']:
            if type(usage.get(k))is int:totals[k]+=usage[k]
        if not all(type(usage.get(k))is int for k in ['prompt_tokens','completion_tokens']):unknown+=1
        bindings[str(path.relative_to(WORKSPACE))]=sha(path)
    return dict(requests=len(bindings),known_token_subtotals=dict(totals),unknown_usage_requests=unknown,statuses=dict(statuses)),bindings

def case_ids(rows):
    grouped={a:{r['id']:r for r in rows if r['arm']==a}for a in MAIN}
    ids=sorted(grouped['graph']);cases=[]
    for arm in MAIN[1:]:
        for direction in ['graph_win','text_win','more_evidence_lower_score']:
            eligible=[]
            for qid in ids:
                g=grouped['graph'][qid];b=grouped[arm][qid]
                margin=g['score_lower']-b['score_upper']if direction=='graph_win'else b['score_lower']-g['score_upper']
                if direction=='more_evidence_lower_score'and g['necessary_evidence_recall']<=b['necessary_evidence_recall']:continue
                if margin>0:eligible.append((margin,qid))
            if eligible:
                margin,qid=sorted(eligible,key=lambda v:(-v[0],v[1]))[0]
                cases.append(dict(id=qid,other_arm=arm,selection=direction,identified_margin=margin))
    return cases

def figures(out,summary,rows):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    import numpy as np
    plt.rcParams.update({'font.size':10,'axes.spines.top':False,'axes.spines.right':False})
    colors=['#186C79','#DA985A','#5075A5','#8A70A3','#619C84']
    def store(fig,name):
        fig.tight_layout()
        for ext in ['png','pdf']:fig.savefig(out/(name+'.'+ext),dpi=200)
        plt.close(fig)
    for arms,name in [(MAIN,'main_eas'),(ABS,'ablations_eas')]:
        fig,ax=plt.subplots(figsize=(8,3.8))
        for i,a in enumerate(arms):
            s=summary['by_arm'][a];lo=100*s['score_lower'];hi=100*s['score_upper']
            ax.barh(i,lo,color=colors[i],alpha=.9)
            ax.barh(i,hi-lo,left=lo,color=colors[i],alpha=.25,hatch='///')
            ax.text(hi+1,i,f'{lo:.1f}–{hi:.1f}',va='center',fontsize=9)
        ax.set(yticks=range(len(arms)),yticklabels=[LABELS[a]for a in arms],xlim=(0,100),xlabel='EAS (0–100); hatched = unknown identification range')
        ax.invert_yaxis();ax.grid(axis='x',alpha=.15);store(fig,name)
    for arms,name in [(MAIN,'four_types_main'),(ABS,'four_types_ablations')]:
        fig,axes=plt.subplots(1,4,figsize=(14,4),sharey=True)
        for ax,t in zip(axes,['S0','S1','M0','M1']):
            for i,a in enumerate(arms):
                s=summary['by_type'][a][t];lo=100*s['score_lower'];hi=100*s['score_upper']
                ax.bar(i,lo,color=colors[i]);ax.bar(i,hi-lo,bottom=lo,color=colors[i],alpha=.25,hatch='///')
            ax.set(title=f'{t} (n=50)',xticks=range(len(arms)),xticklabels=[LABELS[a]for a in arms],ylim=(0,100))
            ax.tick_params(axis='x',labelrotation=65,labelsize=8);ax.grid(axis='y',alpha=.15)
        axes[0].set_ylabel('EAS identification bounds');store(fig,name)
    specs=[(family,v)for family,values in summary['comparisons'].items()for v in values]
    fig,ax=plt.subplots(figsize=(9,4.5))
    for i,(family,v)in enumerate(specs):
        ci=v['uncertainty_envelope_ci95'];lo=v['difference_lower'];hi=v['difference_upper']
        ax.plot([100*ci[0],100*ci[1]],[i,i],color='#AEBBC3',linewidth=2)
        ax.plot([100*lo,100*hi],[i,i],color='#186C79',linewidth=7,solid_capstyle='butt')
    ax.axvline(0,color='black',linewidth=.8);ax.axvline(5,color='#DA985A',linestyle=':',linewidth=1)
    ax.set(yticks=range(len(specs)),yticklabels=[f"{family}: {v['comparison']}"for family,v in specs],xlabel='Graph minus comparator (EAS points)\nThick: identification range; thin: cluster bootstrap95% envelope')
    ax.invert_yaxis();ax.grid(axis='x',alpha=.15);store(fig,'paired_effects')
    fig,axes=plt.subplots(1,2,figsize=(11,4))
    for i,a in enumerate(MAIN):
        s=summary['by_arm'][a];x=100*s['necessary_evidence_recall'];lo=100*s['score_lower'];hi=100*s['score_upper']
        axes[0].plot([x,x],[lo,hi],color=colors[i],linewidth=3)
        axes[0].scatter([x],[(lo+hi)/2],s=45,color=colors[i],label=LABELS[a])
        own=[r for r in rows if r['arm']==a];bins=[]
        for left,right in [(0,.25),(.25,.5),(.5,.75),(.75,1.000001)]:
            sample=[r for r in own if left<=r['necessary_evidence_recall']<right]
            if sample:bins.append(((left+min(right,1))/2,100*statistics.mean(r['score_lower']for r in sample),100*statistics.mean(r['score_upper']for r in sample),len(sample)))
        axes[1].plot([100*b[0]for b in bins],[b[1]for b in bins],marker='o',color=colors[i])
        axes[1].fill_between([100*b[0]for b in bins],[b[1]for b in bins],[b[2]for b in bins],color=colors[i],alpha=.15)
    for ax in axes:ax.set(xlim=(0,100),ylim=(0,100),xlabel='Delivered registered evidence recall (%)',ylabel='EAS identification bounds');ax.grid(alpha=.15)
    axes[0].set_title('Method means; descriptive');axes[0].legend(fontsize=8)
    axes[1].set_title('Within-method evidence bins; descriptive')
    store(fig,'evidence_and_eas')

def run(output):
    analysis=GEN/'analysis_001';summary=read(analysis/'summary.json');rows=read(analysis/'session-metrics.json')
    if summary['sessions']!=1400 or len(rows)!=1400 or sha(GEN/'scoring_001/completion.json')!=summary['scoring_completion_sha256']:raise ValueError('only closed full1400 analysis accepted')
    out=ARCHIVE/'reports'/output;out.mkdir(parents=True,exist_ok=False);figs=out/'figures';figs.mkdir()
    old={m:read(CURRENT/'basic_search_200_20261019_001'/m/'analysis_001/summary.json')for m in ['qwen3-8b','qwen3-14b']}
    asset=read(WORKSPACE/'graduation-thesis-materials/graduation-manuscript/assets/chapter2/model_scales/source-manifest.json')
    historical_bindings={};asset_bindings={k.replace('\\','/'):v for k,v in asset['input_sha256'].items()}
    for model in old:
        path=CURRENT/'basic_search_200_20261019_001'/model/'analysis_001/summary.json';h=sha(path)
        if asset_bindings[path.relative_to(WORKSPACE).as_posix()]!=h:raise ValueError('historical manuscript binding drift')
        historical_bindings[str(path.relative_to(WORKSPACE))]=h
    table=[]
    for arm in ['none','basic_search','bm25','e5','hybrid','graph','bge_m3','bm25_bge_m3','bm25_parent']:
        row=dict(method=arm)
        for model,data in old.items():row[model+'_historical']=interval(data['by_arm'][arm])if arm in data['by_arm']else 'not run'
        row['qwen3_14b_round2']=interval(summary['by_arm'][arm])if arm in summary['by_arm']else 'not rerun'
        table.append(row)
    write_csv(out/'nine_method_batches.csv',table)
    newtable=[dict(method=arm,eas=interval(v),strict_valid_percent=interval(v,'complete'),n=v['n'],generation_statuses=v['generation_statuses'],judge_statuses=v['judge_statuses'],
        evidence_recall_percent=100*v['necessary_evidence_recall'],tool_calls=v['tool_calls'],mean_characters=v['mean_characters'],p95_seconds=v['p95_seconds'])for arm,v in summary['by_arm'].items()]
    write_csv(out/'new_qa_methods.csv',newtable)
    effects=[dict(family=f,**v)for f,values in summary['comparisons'].items()for v in values];write_csv(out/'paired_comparisons.csv',effects)
    actual={};receipt_bindings={}
    for name,paths in [('generation',sorted(GEN.glob('*/generation/*/requests/*.json'))),('judge',sorted((GEN/'scoring_001/sessions').glob('*/*/requests/*.json')))]:
        actual[name],bindings=receipt_usage(paths);receipt_bindings.update(bindings)
    actual.update(price='Actual private proxy input/output prices unavailable; no currency amount invented',formula='sum(input_tokens/1e6*input_price + output_tokens/1e6*output_price) across generation and judging',
        count_policy='Canonical1400 receipt set once. Copied first1000 scores are not additional calls. Unknown usage is missing, not zero.')
    save(out/'actual_usage.json',actual);save(out/'request_bindings.json',receipt_bindings)
    chosen=case_ids(rows);save(out/'case_selection.json',dict(policy='Post hoc deterministic examples: maximum identified margin, tie question ID; report both directions and more-evidence/lower-score. No changes to aggregate comparisons.',cases=chosen))
    annotations={a['id']:a for a in read(DATASET/'scoring/annotations.json')};qs={q['id']:q['question']for q in public_questions()};by={(r['arm'],r['id']):r for r in rows}
    lines=['# 端到端案例（结果后选择，仅解释用）','', '完整总体、负例与不显著结果仍按冻结统计报告。按最大已识别差值选例，不代表发生频率；引用送达不代表语义蕴含。','']
    for case in chosen:
        qid=case['id'];lines += [f"## {qid}: graph vs {case['other_arm']} — {case['selection']}",'',qs[qid],'',json.dumps(annotations[qid]['required_points'],ensure_ascii=False,indent=2),'']
        for arm in ['graph',case['other_arm']]:
            r=read(GEN/arm/'generation'/qid/'result.json');s=read(GEN/'scoring_001/sessions'/arm/qid/'result.json');m=by[(arm,qid)]
            lines += [f'### {arm}','',f"EAS={100*m['score_lower']:.2f}–{100*m['score_upper']:.2f}；证据召回={100*m['necessary_evidence_recall']:.2f}%；生成={r['status']}",'',r['answer']or '（无可交付回答）','',json.dumps(dict(references=r['references'],judgment=s.get('judgment'),metrics=s['metrics']),ensure_ascii=True,indent=2),'']
    (out/'cases.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    figures(figs,summary,rows)
    report=['# 第二轮端到端结果与论文使用说明','', '7方法×200题=1400会话已闭合；失败0分，未知保留上下界，全200题保留分母。下列区间是未知识别范围，不是置信区间。','',
        '|方法|EAS|严格完整有效率%|','|---|---:|---:|']
    for r in newtable:report.append(f"|{r['method']}|{r['eas']}|{r['strict_valid_percent']}|")
    report+=['','## 预定义配对比较','', '|比较族|比较|EAS差值识别范围|95%知识组bootstrap包络|Holm p上界|正向统计支持|','|---|---|---:|---:|---:|---|']
    for e in effects:report.append(f"|{e['family']}|{e['comparison']}|[{100*e['difference_lower']:.2f}, {100*e['difference_upper']:.2f}]|[{100*e['uncertainty_envelope_ci95'][0]:.2f}, {100*e['uncertainty_envelope_ci95'][1]:.2f}]|{e['holm_p_upper']:.6g}|{e['statistical_positive_identified']}|")
    report+=['','主比较4项与消融2项分别Holm校正，知识组24个；实际意义阈值5分以差值下界判定。没有用四类型结果再选最优方法。',
        '','## 批次和结论边界','',
        '- nine_method_batches.csv并列历史8B、历史14B与本轮14B；空格明确未运行。历史来源含旧基线复用和基础搜索后补；不合并分母，不对跨批次差值做本轮显著性宣称。',
        '- 固定查询6000字符召回与端到端Agent多次自主调用的证据召回不同，分别保留。证据取得不等于回答正确；图表evidence_and_eas是描述性对应关系。',
        '- 200题已暴露，完整图和指标曾在观察旧结果后修订；本轮结果不能宣称未见泛化或全局最优。32B无结果。',
        '- 回答和裁判均为同系列14B。人工80回答、图50节点/50边/30别名仍待真实标签；合成校准通过不代表人工验证的准确率。',
        '- 新留出改为40题、四类各10。280会话仅在人审和重叠审查到位、独立协议冻结后运行。目前没有留出成绩。',
        '- 本次Unicode交付故障用独立视图留痕，原件与所有API回执保留；生成失败计0，没有修改回答、补问模型或重试评分。',
        '', '## 可纳入正文的写作范围','',
        'RQ1使用本轮五方法配对比较；RQ2使用两项新增消融，并与固定查询机制trace对照；RQ3明确人工核验和留出结果尚缺，不把空表写成证据。',
        '本目录提供CSV、独立PNG/PDF和结果后解释案例。历史论文及其assets保持原样，正式纳入前须保留上述批次、未知、同系列裁判与暴露题库说明。','']
    (out/'results.md').write_text('\n'.join(report)+'\n',encoding='utf-8')
    save(out/'manifest.json',dict(analysis_sha256=sha(analysis/'summary.json'),session_metrics_sha256=sha(analysis/'session-metrics.json'),
        historical_sha256=historical_bindings,script_sha256=sha(Path(__file__)),files={str(p.relative_to(out)):sha(p)for p in out.rglob('*')if p.is_file()}))
    print('Closed QA tables,6 figure pairs,usage and balanced post-hoc cases exported')

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--output',default='qa_closed_001');a=ap.parse_args();run(a.output)
