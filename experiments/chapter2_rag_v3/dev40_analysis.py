"""Dev-only dual-judge results and descriptive robustness, without changing audit gates."""
from collections import defaultdict
import csv
from html import escape
import itertools
import math
from pathlib import Path
import random
import statistics

import dev40_optimization as dev
import dev40_scoring as scoring
import scoring as core
from judge_api_adapter import digest
from judge_contract import calculate
from judge_statistics import ordinal_agreement, dual_eas, metric_error


def adjacent_agreement(pairs):
    result=ordinal_agreement(pairs)
    known=[(x,y) for x,y in pairs if type(x) in (int,float) and type(y) in (int,float) and x in (0,.25,.5,.75,1) and y in (0,.25,.5,.75,1)]
    result['within_one_level']=sum(abs(x-y)<=.25 for x,y in known)/len(known) if known else None
    result['more_than_one_level']=sum(abs(x-y)>.25 for x,y in known)
    result['adjacent_definition']='Absolute score difference <=0.25, including exact matches; Unknown/N/A excluded and counted separately'
    return result


def ranks(values):
    order=sorted(range(len(values)),key=lambda i:values[i],reverse=True);result=[0.]*len(values);pos=0
    while pos<len(order):
        end=pos+1
        while end<len(order) and abs(values[order[end]]-values[order[pos]])<1e-9:end+=1
        for k in order[pos:end]:result[k]=(pos+1+end)/2
        pos=end
    return result


def rank_agreement(left,right):
    if len(left)!=len(right) or len(left)<2:return dict(n=len(left),spearman=None,kendall_tau_b=None)
    a=ranks(left);b=ranks(right);ma=statistics.mean(a);mb=statistics.mean(b)
    denominator=math.sqrt(sum((x-ma)**2 for x in a)*sum((y-mb)**2 for y in b))
    concordant=discordant=tie_left=tie_right=0
    for i,j in itertools.combinations(range(len(a)),2):
        x=a[i]-a[j];y=b[i]-b[j]
        if x==0 and y==0:continue
        if x==0:tie_left+=1
        elif y==0:tie_right+=1
        elif x*y>0:concordant+=1
        else:discordant+=1
    kd=math.sqrt((concordant+discordant+tie_left)*(concordant+discordant+tie_right))
    return dict(n=len(a),spearman=sum((x-ma)*(y-mb) for x,y in zip(a,b))/denominator if denominator else None,
        kendall_tau_b=(concordant-discordant)/kd if kd else None,
        concordant_pairs=concordant,discordant_pairs=discordant,tied_left_pairs=tie_left,tied_right_pairs=tie_right)


def mean_interval(values,resamples=2000,seed=20261024):
    if not values or any(v is None for v in values):return None
    rng=random.Random(seed);means=sorted(statistics.mean(rng.choices(values,k=len(values))) for _ in range(resamples))
    return [means[int(.025*(resamples-1))],means[int(.975*(resamples-1))]]


def dimension_pairs(items,left,right):
    pairs={k:[] for k in ('K','F','A')}
    for i in items:
        sid=i['sample_id']
        if sid not in left or sid not in right:continue
        x=left[sid];y=right[sid];xp={z['criterion_id']:z['score'] for z in x['points']};yp={z['criterion_id']:z['score'] for z in y['points']}
        pairs['K'].extend((xp[c['criterion_id']],yp[c['criterion_id']]) for c in i['criteria'])
        pairs['F'].append((x['fact_gate'],y['fact_gate']))
        if i['conditional']:pairs['A'].append((x['applicability_gate'],y['applicability_gate']))
    return {k:adjacent_agreement(v) for k,v in pairs.items()}


def reference_robustness():
    result={}
    for batch,path in [('calibration',core.ROOT),('audit',core.ROOT/'audit')]:
        p=core.read(path/('calibration.json' if batch=='calibration' else 'packet.json'))
        labels={'human':{r['sample_id']:r for r in core.rows(path/'human/scores.jsonl')}}
        for j in core.JUDGES:labels[j]={r['sample_id']:r for r in core.rows(path/'results'/(j+'.jsonl'))}
        original=core.read(path/'results/summary.json')
        result[batch]=dict(questions=6 if batch=='calibration' else 4,answers=len(p['items']),
            human_agreement={j:dimension_pairs(p['items'],labels['human'],labels[j]) for j in core.JUDGES},
            EAS_errors={j:{metric:original['agreement'][j][metric] for metric in ('EAS_arith','EAS_geo')} for j in core.JUDGES},
            dual_mean_EAS_errors=original['dual_mean_vs_human'],
            original_summary_sha256=core.sha(path/'results/summary.json'),
            original_audit_decision='fail' if batch=='audit' else None)
    return result


def report(verify=True):
    authority=scoring.guard_operational();packet=core.read(scoring.ROOT/'packet.json')
    labels,failed_attempts=scoring.collect(packet,verify=verify)
    byid={i['sample_id']:i for i in packet['items']};private={r['sample_id']:r for r in packet['private']}
    items_by_key={(r['config_id'],r['question_id']):byid[r['sample_id']] for r in packet['private']}
    templates={r['question_id']:byid[r['sample_id']] for r in packet['private']}
    configs=core.read(dev.ROOT/'candidate_matrix.json')['configurations'];short=core.read(dev.ROOT/'shortlist.json')
    configs=[c for c in configs if c['config_id'] in short['active_configuration_ids']]
    questions=[q['id'] for q in core.read(dev.QUESTIONS)]
    rows=[];groups=[];selection=[];answer_values={};disputes=[]
    for cfg in configs:
        metrics={j:[] for j in (*core.JUDGES,'dual_mean')}
        for qid in questions:
            i=items_by_key.get((cfg['config_id'],qid));present=i is not None
            if not present:i=dict(templates[qid],generation_failed=False)
            sid=i['sample_id'] if present else None
            values={j:scoring.answer_metrics(i,labels[j].get(sid) if present else None) for j in core.JUDGES}
            values['dual_mean']=dual_eas(list(values.values()))
            answer_values[(cfg['config_id'],qid)]=values
            for j,value in values.items():
                metrics[j].append(value)
                rows.append(dict(config_id=cfg['config_id'],model=cfg['logical_model'],method=cfg['method_id'],question_id=qid,
                    sample_id=sid,judge=j,generation_status=private[sid]['status'] if present else 'not_run',
                    judge_record_present=(sid in labels.get(j,{})) if j!='dual_mean' else all(sid in labels[x] for x in core.JUDGES),
                    **value))
            selection.append(dict(schema_version=packet['schema_version'],config_id=cfg['config_id'],question_id=qid,
                generation_failed=i['generation_failed'] if present else False,
                judge_eas_arith_bounds={j:values[j]['eas_arith_bounds'] for j in core.JUDGES},
                judge_eas_geo_bounds={j:values[j]['eas_geo_bounds'] for j in core.JUDGES},
                generation_present=present,judges_complete=present and (i['generation_failed'] or all(sid in labels[j] for j in core.JUDGES))))
            if present and all(sid in labels[j] for j in core.JUDGES):
                x,y=[labels[j][sid] for j in core.JUDGES]
                f=[x['fact_gate'],y['fact_gate']];a=[x['applicability_gate'],y['applicability_gate']]
                numeric=lambda z:all(type(t) in (int,float) for t in z)
                if numeric(f) and f[0]!=f[1] or i['conditional'] and numeric(a) and a[0]!=a[1]:
                    disputes.append(dict(sample_id=sid,question_id=qid,model=cfg['logical_model'],method=cfg['method_id'],
                        F=f,A=a,large_fact_gap=numeric(f) and abs(f[0]-f[1])>=.5,
                        severe_fact_opposition=numeric(f) and min(f)<=.25 and max(f)>=.75,
                        large_condition_gap=i['conditional'] and numeric(a) and abs(a[0]-a[1])>=.5,
                        reasons={j:labels[j][sid].get('reason','') for j in core.JUDGES},
                        EAS_arith=[values[j]['EAS_arith'] for j in core.JUDGES],EAS_geo=[values[j]['EAS_geo'] for j in core.JUDGES]))
        groups.append(dict(config_id=cfg['config_id'],model=cfg['logical_model'],method=cfg['method_id'],parameters=cfg['candidate_parameters'],
            generated=sum((cfg['config_id'],q) in items_by_key for q in questions),
            generation_failed=sum(items_by_key[(cfg['config_id'],q)]['generation_failed'] for q in questions if (cfg['config_id'],q) in items_by_key),
            judged={j:sum(items_by_key[(cfg['config_id'],q)]['sample_id'] in labels[j] for q in questions if (cfg['config_id'],q) in items_by_key) for j in core.JUDGES},
            summaries={j:core.summarize(m) for j,m in metrics.items()}))
    rankings=[]
    for model in sorted({c['logical_model'] for c in configs}):
        for metric in ('EAS_arith','EAS_geo'):
            for scope in ('main9','all13'):
                relevant=[g for g in groups if g['model']==model and (scope=='all13' or g['method'] not in dev.GRAPH-{'graph'})]
                complete=all(g['summaries'][j][metric] is not None for g in relevant for j in (*core.JUDGES,'dual_mean'))
                if not complete:
                    rankings.append(dict(model=model,metric=metric,scope=scope,status='incomplete_unknowns_preserved'));continue
                means={j:{g['method']:g['summaries'][j][metric] for g in relevant} for j in (*core.JUDGES,'dual_mean')}
                methods=sorted(means['gpt_sol']);ranked={j:sorted(methods,key=lambda m:(-means[j][m],m)) for j in means}
                concordance=rank_agreement([means['gpt_sol'][m] for m in methods],[means['deepseek_flash'][m] for m in methods])
                conflicts=[]
                for x,y in itertools.combinations(relevant,2):
                    diffs={j:means[j][x['method']]-means[j][y['method']] for j in core.JUDGES}
                    if diffs['gpt_sol']*diffs['deepseek_flash']>=0:continue
                    intervals={}
                    for j in core.JUDGES:
                        delta=[answer_values[(x['config_id'],q)][j][metric]-answer_values[(y['config_id'],q)][j][metric] for q in questions]
                        intervals[j]=mean_interval(delta)
                    conflicts.append(dict(method_x=x['method'],method_y=y['method'],mean_x_minus_y=diffs,
                        paired_question_bootstrap_intervals=intervals,
                        opposite_nonzero_descriptive_intervals=all(b and b[0]*b[1]>0 for b in intervals.values())))
                rankings.append(dict(model=model,metric=metric,scope=scope,status='complete',means=means,rankings=ranked,
                    judge_rank_agreement=concordance,opposite_mean_pairs=conflicts,
                    top_method_agrees=ranked['gpt_sol'][0]==ranked['deepseek_flash'][0]))
    errors={}
    for metric in ('EAS_arith','EAS_geo'):
        pairs=[(r['question_id'],answer_values[(r['config_id'],r['question_id'])]['deepseek_flash'][metric]-answer_values[(r['config_id'],r['question_id'])]['gpt_sol'][metric])
            for r in packet['private'] if all(answer_values[(r['config_id'],r['question_id'])][j][metric] is not None for j in core.JUDGES) and not byid[r['sample_id']]['generation_failed']]
        errors[metric]=metric_error(pairs)
    model_diagnostics={}
    for model in sorted({r['model'] for r in packet['private']}):
        subset=[byid[r['sample_id']] for r in packet['private'] if r['model']==model]
        model_errors={}
        for metric in ('EAS_arith','EAS_geo'):
            pairs=[(r['question_id'],answer_values[(r['config_id'],r['question_id'])]['deepseek_flash'][metric]-answer_values[(r['config_id'],r['question_id'])]['gpt_sol'][metric])
                for r in packet['private'] if r['model']==model and not byid[r['sample_id']]['generation_failed']
                and all(answer_values[(r['config_id'],r['question_id'])][j][metric] is not None for j in core.JUDGES)]
            model_errors[metric]=metric_error(pairs)
        model_diagnostics[model]=dict(interjudge_KFA=dimension_pairs(subset,labels['gpt_sol'],labels['deepseek_flash']),
            interjudge_EAS=model_errors,professional_disagreement_flags=sum(r['model']==model for r in disputes),
            large_fact_gaps=sum(r['model']==model and r['large_fact_gap'] for r in disputes),
            large_condition_gaps=sum(r['model']==model and r['large_condition_gap'] for r in disputes),
            severe_fact_oppositions=sum(r['model']==model and r['severe_fact_opposition'] for r in disputes))
    model_comparison=[]
    for method in dev.METHODS:
        left=next(c for c in configs if c['logical_model']=='qwen3-8b' and c['method_id']==method)
        right=next(c for c in configs if c['logical_model']=='qwen3-14b' and c['method_id']==method)
        comparisons={}
        for judge in (*core.JUDGES,'dual_mean'):
            comparisons[judge]={}
            for metric in ('EAS_arith','EAS_geo'):
                pairs=[(answer_values[(left['config_id'],qid)][judge][metric],answer_values[(right['config_id'],qid)][judge][metric]) for qid in questions]
                known=all(x is not None and y is not None for x,y in pairs)
                delta=[y-x for x,y in pairs] if known else []
                comparisons[judge][metric]=dict(n=40 if known else 0,mean_14b_minus_8b=statistics.mean(delta) if known else None,
                    paired_question_bootstrap_interval=mean_interval(delta) if known else None)
        model_comparison.append(dict(method=method,comparisons=comparisons))
    from dev40_recovery import active_recovery
    recovery=active_recovery(dev.ROOT);recovery_effect=None
    if recovery:
        key=recovery['config_id'];qid=recovery['question_id'];details={}
        for judge in (*core.JUDGES,'dual_mean'):
            details[judge]={}
            for metric in ('EAS_arith','EAS_geo'):
                recovered=answer_values[(key,qid)][judge][metric]
                baseline=[0 if q==qid else answer_values[(key,q)][judge][metric] for q in questions]
                effective=[answer_values[(key,q)][judge][metric] for q in questions]
                details[judge][metric]=dict(baseline_40_mean=statistics.mean(baseline) if all(v is not None for v in baseline) else None,
                    effective_40_mean=statistics.mean(effective) if all(v is not None for v in effective) else None,
                    recovered_answer_EAS=recovered,mean_change_from_single_recovery=recovered/40 if recovered is not None else None)
        recovery_effect=dict(receipt=recovery,metrics=details,original_failure_retained=True)
    generation_usage=[]
    for cfg in configs:
        observed=[]
        for m in packet['private']:
            if m['config_id']!=cfg['config_id']:continue
            file=core.DEFAULT_RUN/m['source_file']
            if core.sha(file)!=m['source_sha256']:raise ValueError('Generation usage source binding changed')
            raw=core.read(file);observed.append((len(raw.get('tool_events',[])),raw.get('knowledge_characters',0)))
        generation_usage.append(dict(model=cfg['logical_model'],method=cfg['method_id'],observed=len(observed),
            with_tool_calls=sum(c>0 for c,_ in observed),with_evidence_characters=sum(chars>0 for _,chars in observed),
            mean_tool_calls=statistics.mean(c for c,_ in observed) if observed else None,
            mean_knowledge_characters=statistics.mean(chars for _,chars in observed) if observed else None))
    refs=reference_robustness()
    output=dict(updated_utc=core.now(),schema_version=packet['schema_version'],freeze_id=authority['freeze_id'],
        original_audit_passed=False,operational_authorized=True,test160_started=False,judged_records={j:len(v) for j,v in labels.items()},
        failed_attempts=failed_attempts,by_method_model=groups,rankings=rankings,answers=rows,
        interjudge_KFA=dimension_pairs(packet['items'],labels['gpt_sol'],labels['deepseek_flash']),interjudge_EAS=errors,
        interjudge_by_model=model_diagnostics,
        model_comparison=model_comparison,model_comparison_interpretation='Exploratory paired Dev40 differences (14B minus 8B), retaining generation-failure zeros and full-40 denominator; no confirmatory significance claim.',
        infrastructure_recovery_effect=recovery_effect,
        generation_tool_usage=generation_usage,tool_usage_interpretation='Observed behavior under the unchanged autonomous QA protocol; method permission does not force a tool call. Preserve failures and disclose evidence use when interpreting model/method scores.',
        professional_disagreements=disputes,
        disagreement_definition='Numerical F/A differences are flags, not proof of professional error. Reasons and original sources require substantive review; omissions must not mechanically be penalized twice.',
        reference_robustness=refs,
        ranking_interpretation='Spearman with average tied ranks; Kendall tau-b. Opposite mean pairs and 95% paired-question bootstrap intervals are exploratory, unadjusted diagnostics, not new acceptance gates.',
        parameter_scope='26 selected common-budget configurations; one configuration per method/model. No global optimum claim over the 48 deferred budget variants.',
        source_packet_sha256=core.sha(scoring.ROOT/'packet.json'),source_authorization_sha256=core.sha(core.ROOT/'operational_use.json'))
    folder=dev.ROOT/'results';core.write(folder/'scoring_summary.json',output);core.write(folder/'selection_input.json',selection)
    core.write(core.ROOT/'results/robustness.json',refs)
    # Only large F/A differences are expanded; adjacent differences remain in JSON.
    major=[d for d in disputes if d['large_fact_gap'] or d['large_condition_gap']]
    annotations={a['id']:a for a in core.read(dev.SPLIT/'gold/dev40/annotations.json')}
    evidence=core.read(dev.SPLIT/'gold/dev40/evidence.json')
    human={r['sample_id']:r for base in (core.ROOT,core.ROOT/'audit') for r in core.rows(base/'human/scores.jsonl')}
    cards=''
    for d in major:
        i=byid[d['sample_id']];a=annotations[d['question_id']]
        claim_html=''.join('<li>'+escape(c['claim'])+'</li>' for c in i['criteria'])
        sources_html=''.join('<details><summary>'+escape(evidence[e]['path'])+' : '+str(evidence[e]['line_start'])+'–'+str(evidence[e]['line_end'])+'</summary><pre>'+escape(evidence[e]['excerpt'])+'</pre></details>' for e in a['required_evidence_ids'])
        h=human.get(d['sample_id']);human_text=('人工原分 F='+str(h['fact_gate'])+'；A='+str(h['applicability_gate'])) if h else '该回答没有人工参考评分'
        cards+='<article data-model="'+escape(d['model'])+'"><h2>'+escape(d['model']+' / '+d['question_id']+' / '+d['method'])+'</h2><p>'+escape(i['question'])+'</p><h3>原回答</h3><pre>'+escape(i['answer'])+'</pre><h3>Gold必要点</h3><ol>'+claim_html+'</ol><p>GPT / DeepSeek：F='+escape(str(d['F']))+'；A='+escape(str(d['A']))+'。'+escape(human_text)+'</p><p>GPT备注：'+escape(d['reasons']['gpt_sol'])+'</p><p>DeepSeek备注：'+escape(d['reasons']['deepseek_flash'])+'</p>'+sources_html+'</article>'
    (folder/'professional_review.html').write_text('<!doctype html><meta charset="utf-8"><title>Dev40专业评分分歧</title><style>body{font:16px system-ui;max-width:1100px;margin:30px auto}article{border-top:1px solid #aaa;padding:20px 0}pre{white-space:pre-wrap;line-height:1.6}p{line-height:1.6}</style><h1>Dev40 · 事实与条件评分分歧</h1><p>仅展开F或A相差至少0.5的现有记录。数值差异不等于已证实专业错判；必要点遗漏与实质性错误需分开。这里不修改任何评分，不作为Prompt优化反馈。原审计未通过的记录保持不变。</p><p><a href="scoring.html">双指标与方法排序</a> · <a href="scoring_summary.json">全部分歧统计</a></p>'+cards,encoding='utf-8')
    fields=sorted({k for r in rows for k in r})
    with (folder/'scores.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=fields);writer.writeheader();writer.writerows(rows)
    body=''
    def num(x):return 'Unknown' if x is None else '%.3f'%x
    for g in groups:
        for j,v in g['summaries'].items():
            body+='<tr data-model="%s"><td>%s</td><td>%s</td><td>%s</td><td>%d/40</td><td>%d</td><td>%s</td><td>%s</td><td>%s</td></tr>'%(g['model'],g['model'],g['method'],j,g['generated'],g['generation_failed'],num(v['EAS_arith']),num(v['EAS_geo']),num(v['Strict']) if 'Strict' in v else 'N/A')
    rankbody=''
    for r in rankings:
        if r['status']!='complete':continue
        c=r['judge_rank_agreement']
        rankbody+='<p>%s / %s / %s：Spearman %s；Kendall %s。GPT：%s；DeepSeek：%s。</p>'%(r['model'],r['metric'],r['scope'],num(c['spearman']),num(c['kendall_tau_b']),' > '.join(r['rankings']['gpt_sol']),' > '.join(r['rankings']['deepseek_flash']))
    reference_body=''
    for batch,v in refs.items():
        for judge,stats in v['human_agreement'].items():
            for dimension,s in stats.items():
                reference_body+='<tr><td>%s</td><td>%s</td><td>%s</td><td>%d</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>'%(batch,judge,dimension,s['n'],num(s['exact']),num(s['within_one_level']),num(s['quadratic_kappa']),num(s['mae']),num(s['bias_right_minus_left']))
    reference_html='<h2>人工参考稳健性：校准与独立审计分开</h2><p>相邻一致包含完全一致，定义为绝对差≤0.25。K按必要点，F按回答，A仅条件回答；Unknown不填补。校准A样本量小且人工边际单一，Kappa=0不能解读为没有相邻一致。以下是事后补充描述，不替换原验收门槛。</p><table><tr><th>数据</th><th>裁判</th><th>维度</th><th>n</th><th>完全一致</th><th>相邻一致</th><th>二次加权Kappa</th><th>MAE</th><th>Bias</th></tr>'+reference_body+'</table>'
    errorbody=''
    for batch,v in refs.items():
        for judge,errors in dict(v['EAS_errors'],dual_mean=v['dual_mean_EAS_errors']).items():
            for metric,s in errors.items():
                errorbody+='<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>'%(batch,judge,metric,num(s['mae']),num(s['bias_right_minus_left']))
    reference_html+='<h3>相对人工EAS误差（0–100分）</h3><p>双均值先逐答平均，再计算相对人工误差。两个人工数据集分开，当前开发回答没有新增人工真值。</p><table><tr><th>数据</th><th>裁判</th><th>指标</th><th>MAE</th><th>Bias</th></tr>'+errorbody+'</table>'
    diagnostic_rows='';metric_rows=''
    for model,stats in model_diagnostics.items():
        for dimension,s in stats['interjudge_KFA'].items():
            diagnostic_rows+='<tr data-diagnostic-model="%s"><td>%s</td><td>%s</td><td>%d</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>'%(model,model,dimension,s['n'],num(s['exact']),num(s['within_one_level']),num(s['quadratic_kappa']),num(s['mae']),num(s['bias_right_minus_left']))
        for metric,s in stats['interjudge_EAS'].items():
            metric_rows+='<tr data-diagnostic-model="%s"><td>%s</td><td>%s</td><td>%d</td><td>%s</td><td>%s</td></tr>'%(model,model,metric,s['identified_pairs'],num(s['mae']),num(s['bias_right_minus_left']))
    diagnostic_html='<h2>分模型裁判差异</h2><p>这是GPT与DeepSeek之间的差异，不是相对人工的准确率。Bias为DeepSeek减GPT。K按必要点；F按回答；A仅条件回答。未知配对另见JSON；没有AI评分的生成失败不计入一致性样本。</p><table><tr><th>模型</th><th>维度</th><th>n</th><th>完全一致</th><th>相邻一致</th><th>二次加权Kappa</th><th>MAE</th><th>Bias</th></tr>'+diagnostic_rows+'</table><table><tr><th>模型</th><th>指标</th><th>n</th><th>MAE</th><th>Bias</th></tr>'+metric_rows+'</table>'
    paired_rows=''
    for comparison in model_comparison:
        values=comparison['comparisons']['dual_mean']
        cells=''
        for metric in ('EAS_arith','EAS_geo'):
            interval=values[metric]['paired_question_bootstrap_interval']
            cells+='<td>'+num(values[metric]['mean_14b_minus_8b'])+'</td><td>'+('[%s, %s]'%tuple(num(v) for v in interval) if interval else 'Unknown')+'</td>'
        paired_rows+='<tr><td>'+comparison['method']+'</td>'+cells+'</tr>'
    diagnostic_html+='<h2>两模型逐题配对比较</h2><p>下表为逐答双裁判均值的14B减8B，保留40题分母及生成失败零分。区间为按题配对Bootstrap，仅作探索性描述，不宣称确认性显著性。单裁判配对结果保留在JSON。</p><table><tr><th>方法</th><th>算术差</th><th>配对区间</th><th>几何差</th><th>配对区间</th></tr>'+paired_rows+'</table>'
    if recovery_effect:
        recovery_rows=''
        for judge,metrics in recovery_effect['metrics'].items():
            for metric,values in metrics.items():
                recovery_rows+='<tr><td>%s</td><td>%s</td><td>%s</td><td>%s</td><td>%s</td></tr>'%(judge,metric,num(values['baseline_40_mean']),num(values['effective_40_mean']),num(values['mean_change_from_single_recovery']))
        diagnostic_html+='<h2>一次基础设施恢复的影响</h2><p>原ConnectionRefused和零模型响应记录保留；仅E17-02的8B直接作答按授权重放一次原请求正文。主分析采用这一次恢复结果，不择优。<a href="../infrastructure_recovery.json">原失败、恢复与哈希绑定</a>。</p><table><tr><th>裁判</th><th>指标</th><th>原基础实验均值</th><th>恢复后均值</th><th>变化</th></tr>'+recovery_rows+'</table>'
    usage_rows=''
    for g in generation_usage:
        usage_rows+='<tr data-diagnostic-model="%s"><td>%s</td><td>%s</td><td>%d/%d</td><td>%s</td><td>%s</td></tr>'%(g['model'],g['model'],g['method'],g['with_tool_calls'],g['observed'],num(g['mean_tool_calls']),num(g['mean_knowledge_characters']))
    diagnostic_html+='<h2>实际工具采用情况</h2><p>采用相同的自主问答协议，允许模型自主选择是否调用工具。以下为原始生成轨迹统计，保留失败回答。工具方法的权限与预算不等于模型一定取用了证据；解释8B方法得分时须同时考虑采用率。</p><table><tr><th>模型</th><th>方法</th><th>实际调用工具</th><th>平均调用数</th><th>平均证据字符</th></tr>'+usage_rows+'</table>'
    html='''<!doctype html><meta charset="utf-8"><title>Dev40双裁判结果</title><style>body{font:16px system-ui;margin:30px auto;max-width:1500px;padding:15px}td,th{padding:8px;text-align:left}.notice{background:#fff0cf;padding:15px}p{line-height:1.6}</style><h1>Dev40 · 双裁判双指标</h1><p class="notice">原独立审计未通过。研究者在知悉结果后授权继续Dev评分与参数比较；不把原审计改记通过，不调整Prompt或阈值。Test160未启动。</p><p><a href="index.html">生成进度</a> · <a href="scoring_summary.json">完整统计与专业分歧</a> · <a href="scores.csv">逐答双指标</a> · <a href="../../../scoring/audit/results/acceptance.md">原审计</a></p><p>全部40题分母；失败为0，缺失/Unknown保留上下界；未评分时不填补。Strict仅为辅助。当前26候选每方法每模型仅一个共同预算配置，不宣称74候选的全局最优。</p><label>模型 <select id="model"><option value="">全部</option><option>qwen3-8b</option><option>qwen3-14b</option></select></label><table><tr><th>模型</th><th>方法</th><th>裁判</th><th>生成</th><th>失败</th><th>EAS_arith</th><th>EAS_geo</th><th>Strict</th></tr>'''+body+'</table><h2>方法排序稳健性</h2>'+rankbody+'''<script>document.getElementById('model').onchange=e=>document.querySelectorAll('tr[data-model]').forEach(r=>r.hidden=!!e.target.value&&e.target.value!==r.dataset.model)</script>'''
    html=html.replace('<h2>方法排序稳健性</h2>',diagnostic_html+reference_html+'<h2>方法排序稳健性</h2>')
    html=html.replace("querySelectorAll('tr[data-model]')","querySelectorAll('tr[data-model],tr[data-diagnostic-model]')").replace('e.target.value!==r.dataset.model','e.target.value!==(r.dataset.model||r.dataset.diagnosticModel)')
    html=html.replace('<a href="scores.csv">','<a href="professional_review.html">事实/条件大幅分歧</a> · <a href="scores.csv">')
    (folder/'scoring.html').write_text(html,encoding='utf-8')
    print(core.json.dumps(dict(judged_records=output['judged_records'],failed_attempts=len(failed_attempts),professional_disagreement_flags=len(disputes),complete_rankings=sum(r['status']=='complete' for r in rankings))))
    return output
