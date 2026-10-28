"""Current Dev40 generation inventory; never fabricate grades or best parameters."""
from collections import Counter
import csv
from html import escape
import json
from pathlib import Path

import dev40_optimization as dev
from central_execution import DEFAULT_RUN,read,sha,now


def report():
    root=dev.ROOT;matrix=read(root/'candidate_matrix.json');short=read(root/'shortlist.json')
    from dev40_runner import effective_configurations
    configs=effective_configurations([c for c in matrix['configurations'] if c['config_id'] in short['active_configuration_ids']],root)
    from dev40_recovery import active_recovery
    recovery=active_recovery(root)
    qs=read(dev.QUESTIONS);reuse=read(root/'reuse.json') if (root/'reuse.json').exists() else {'answers':[]}
    reused={(r['config_id'],r['question_id']):r for r in reuse['answers']}
    acceptance=DEFAULT_RUN/'evaluation/judges/audit/results/acceptance.json'
    accepted=acceptance.exists() and read(acceptance).get('accepted') is True
    authority=DEFAULT_RUN/'evaluation/judges/operational_use.json'
    operational=authority.exists() and read(authority).get('dev40_scoring_authorized') is True
    grades_file=root/'results/scoring_summary.json'
    grades=read(grades_file) if grades_file.exists() else {}
    scored={g['config_id']:g for g in grades.get('by_method_model',[])}
    scored_answers={(r['config_id'],r['question_id']):r for r in grades.get('answers',[]) if r['judge']=='dual_mean'}
    selections={}
    for file in (root/'results').glob('selected_qwen3_*.json'):
        selections[file.stem.removeprefix('selected_')]=read(file)
    rows=[];groups=[];stale_configs=set()
    for c in configs:
        records=[]
        for q in qs:
            record=reused.get((c['config_id'],q['id']))
            if record:
                file=DEFAULT_RUN/record['source_path']
                if sha(file)!=record['source_sha256']:raise ValueError('Reused answer changed')
                value=read(file);origin='initial_dev120_verified_reuse'
            else:
                file=root/'generation'/c['config_id']/q['id']/'result.json'
                value=read(file) if file.exists() else None;origin='new' if value else 'pending'
            baseline_file=file;baseline_value=value;recovered=False
            if recovery and (c['config_id'],q['id'])==(recovery['config_id'],recovery['question_id']):
                if file!=root/recovery['baseline_file'] or sha(file)!=recovery['baseline_sha256']:
                    raise ValueError('Recovery does not match original baseline')
                file=root/recovery['result_file'];value=read(file);origin='infrastructure_recovery';recovered=True
                if value['config_id']!=c['config_id'] or value['id']!=q['id']:raise ValueError('Recovery answer identity mismatch')
            status=value['status'] if value else 'not_run'
            failed=bool(value) and status!='answered'
            row=dict(config_id=c['config_id'],model=c['logical_model'],method=c['method_id'],question_id=q['id'],
                source=origin,status=status,source_file=str(file.relative_to(DEFAULT_RUN)),
                source_sha256=sha(file) if value else None,generation_failed=failed if value else None,
                EAS_arith=0 if failed else None,EAS_geo=0 if failed else None,
                EAS_arith_bounds=[0,0] if failed else [0,100],EAS_geo_bounds=[0,0] if failed else [0,100],
                score_status='generation_failure_zero' if failed else 'awaiting_validated_judges' if value else 'not_generated',
                baseline_status=baseline_value['status'] if baseline_value else 'not_run',
                recovery_of_baseline=dict(source_file=str(baseline_file.relative_to(DEFAULT_RUN)),source_sha256=sha(baseline_file),
                    status=baseline_value['status']) if recovered else None)
            score=scored_answers.get((c['config_id'],q['id']))
            if recovered and score and score['generation_status']!=status:
                score=None;stale_configs.add(c['config_id'])
            if score and not failed:
                for name in ('arith','geo'):
                    row['EAS_'+name]=score['EAS_'+name];row['EAS_'+name+'_bounds']=score['eas_'+name+'_bounds']
                if score['judge_record_present']:row['score_status']='five_level_dual_judged'
            records.append(row);rows.append(row)
        groups.append(dict(config_id=c['config_id'],model=c['logical_model'],method=c['method_id'],parameters=c['candidate_parameters'],
            expected=40,completed=sum(r['status']!='not_run' for r in records),answered=sum(r['status']=='answered' for r in records),
            failed=sum(r['generation_failed'] is True for r in records),reused=sum(r['source']=='initial_dev120_verified_reuse' for r in records),
            pending=sum(r['status']=='not_run' for r in records),
            EAS_arith=None,EAS_geo=None,
            EAS_arith_bounds=[0,sum(r['EAS_arith_bounds'][1] for r in records)/40],
            EAS_geo_bounds=[0,sum(r['EAS_geo_bounds'][1] for r in records)/40]))
    bymodel={}
    for model in sorted({g['model'] for g in groups}):
        subset=[g for g in groups if g['model']==model]
        bymodel[model]={k:sum(g[k] for g in subset) for k in ('expected','completed','answered','failed','reused','pending')}
    for g in groups:
        if g['config_id'] in scored and g['config_id'] not in stale_configs:
            g['scores']=scored[g['config_id']]['summaries']
            for name in ('arith','geo'):
                g['EAS_'+name]=g['scores']['dual_mean']['EAS_'+name]
                g['EAS_'+name+'_bounds']=g['scores']['dual_mean']['eas_'+name+'_bounds']
    frozen=len(selections)==2 and all(s.get('configurations_frozen') is True for s in selections.values())
    scoring_complete=len(scored)==26 and all(all(g['judged'][j]+g['generation_failed']==40 for j in ('gpt_sol','deepseek_flash')) for g in scored.values())
    output=dict(updated_utc=now(),audit_accepted=accepted,post_audit_operational_authorized=operational,
        active_configurations=configs,endpoint_migration_sha256=sha(root/'endpoint_migration.json') if (root/'endpoint_migration.json').exists() else None,
        experiment_stages=dict(selected_baseline_configurations=26,baseline_sessions=1040,additional_parameter_trials=0,
            deferred_budget_configurations=48,infrastructure_recovery_attempts=1 if recovery else 0),
        infrastructure_recovery=recovery,
        parameter_freeze_allowed=accepted or operational,parameters_frozen=frozen,dual_judge_scoring_complete=scoring_complete,
        selected_by_model=selections,best_configurations={m:{k:v['config_id'] if v else None for k,v in s.get('consensus_configurations',{}).items()} for m,s in selections.items()} or None,by_model=bymodel,candidates=groups,records=rows,
        expected_sessions=1040,completed_sessions=sum(g['completed'] for g in groups),
        current_scope='26 configurations; both models and all 13 methods; 48 other budget candidates deferred',
        score_interpretation='EAS unknown for ungraded answers. Generation failures zero; no unvalidated judge used for parameter selection.',
        test160=dict(started=False,ready=False,blockers=
            ([] if accepted or operational else ['Independent judge audit not accepted; no later operational authorization'])+
            (['Dev40 generation incomplete'] if any(g['pending'] for g in groups) else [])+
            ([] if scoring_complete and frozen else ['Dev40 formal scoring, comparison and parameter freeze incomplete'])+
            ['Test160 execution manifest/runner bindings not yet finalized','Test160 start is not authorized']))
    folder=root/'results';folder.mkdir(exist_ok=True)
    from dev40_runner import update
    update(folder/'summary.json',output)
    with (folder/'answers.csv').open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    body=''
    for g in groups:
        v=g.get('scores',{}).get('dual_mean',{})
        cells=[]
        for name in ('arith','geo'):
            value=v.get('EAS_'+name);bounds=v.get('eas_'+name+'_bounds',g['EAS_'+name+'_bounds'])
            cells.append('%.3f'%value if value is not None else 'Unknown [%.2f, %.2f]'%tuple(bounds))
        body+='<tr data-model="'+g['model']+'"><td>'+g['model']+'</td><td>'+g['method']+'</td><td>'+str(g['completed'])+'/40</td><td>'+str(g['reused'])+'</td><td>'+str(g['answered'])+'</td><td>'+str(g['failed'])+'</td><td>'+str(g['pending'])+'</td><td>'+cells[0]+'</td><td>'+cells[1]+'</td></tr>'
    html='''<!doctype html><meta charset="utf-8"><title>Dev40当前结果</title><style>body{font:16px system-ui;max-width:1300px;margin:35px auto;padding:0 15px}td,th{padding:9px;text-align:left}.notice{background:#fff0cf;padding:16px}</style><h1>Dev40 · 26个首轮候选</h1><p class="notice">独立裁判审计未通过。继续生成，保留失败；不使用未验收裁判冻结最优参数，Test160未启动。</p><p>生成进度 %d / 1040；已核验复用120条初始14B回答。首轮工具预算6000/24000字符，direct无工具。</p><p><a href="../../../../scoring/audit/results/acceptance.md">独立审计报告</a> · <a href="summary.json">完整状态</a> · <a href="answers.csv">逐题CSV</a></p><label>模型 <select id="model"><option value="">全部</option><option>qwen3-8b</option><option>qwen3-14b</option></select></label><table><tr><th>模型</th><th>方法</th><th>完成</th><th>复用</th><th>已回答</th><th>失败</th><th>未运行</th><th>EAS_arith</th><th>EAS_geo</th></tr>%s</table><p>Unknown上下界保留完整40题分母。失败计零，其余未评分项不补分；这里没有最终方法成绩或最优配置声明。</p><script>document.getElementById('model').onchange=e=>document.querySelectorAll('tr[data-model]').forEach(r=>r.hidden=!!e.target.value&&e.target.value!==r.dataset.model)</script>'''%(output['completed_sessions'],body)
    html=html.replace('../../../../scoring/','../../../scoring/')
    if operational:
        html=html.replace('独立裁判审计未通过。继续生成，保留失败；不使用未验收裁判冻结最优参数，Test160未启动。','原独立审计未通过；研究者知悉结果后授权继续使用冻结双裁判开展Dev评分和配置选择。原失败记录保留，Test160未启动。')
        html=html.replace('这里没有最终方法成绩或最优配置声明。','表内EAS为逐答双裁判均值；完整单裁判结果与配置选择见评分页。')
    html=html.replace('<label>模型','<p><a href="scoring.html">双裁判双指标、方法排序与专业分歧</a></p><label>模型')
    if frozen:html=html.replace('<label>模型','<p>两模型13种方法的当前候选配置已冻结：<a href="selected_qwen3_8b.json">8B配置</a> · <a href="selected_qwen3_14b.json">14B配置</a>。Test160执行清单与正式入口仍待绑定，未启动。</p><label>模型')
    (folder/'index.html').write_text(html,encoding='utf-8')
    print(json.dumps(dict(by_model=bymodel,audit_accepted=accepted,parameters_frozen=frozen,test160_started=False)))
    return output
