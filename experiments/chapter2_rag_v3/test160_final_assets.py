"""Generate unified final K/F/A/EAS assets only after audited scoring closure."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import shutil

import numpy as np
import matplotlib.pyplot as plt
import figure_style as st
import single_pass_dev40 as s

R = s.RUN/'results'
A = s.WORKSPACE/'graduation-thesis-materials/graduation-manuscript/assets/chapter2_test160'


def read(p):
    return json.loads(p.read_text(encoding='utf-8-sig'))


def closure_guard(audit):
    if not (audit.get('generation_tasks') == 5120 and audit.get('answered') == 4989
            and audit.get('dual_valid') == audit.get('answered') and audit.get('missing_dual') == 0
            and audit.get('formal_experiment_complete') is True):
        raise RuntimeError('Scoring remains unclosed: final publication is forbidden')


def build():
    closure_guard(read(s.RUN/'test160_runs/closure_audit.json'))
    data = read(R/'test160_results.json')
    factors = read(R/'factor_analysis_provenance.json')
    assert factors['status'] == 'final_closed_diagnostics'
    rows, groups, pairs = data['per_answer'], data['groups'], data['paired']
    assert len(rows) == 5120 and len(groups) == 32
    assert all(r['generation_failed'] or r['evaluation_complete'] for r in rows)
    assert all(r['score']['unknown_items'] == 0 for r in rows)
    assert all(g['EAS_arith'] is not None and g['EAS_geo'] is not None for g in groups)
    fgroups = {(g['mode'], g['model'], g['method']):g for g in factors['groups']}
    for g in groups:
        f = fgroups[g['mode'],g['model'],g['method']]
        for k in ('K','F','A'):
            assert f[k+'_known_n'] == f[k+'_n']
            if not g['generation_failures']:
                assert abs(100*g[k]-f[k+'_bounds'][0]) < 1e-8
            else:
                assert f[k+'_n'] == sum(not r['generation_failed'] and (k!='A' or r['conditional']) for r in rows if (r['mode'],r['model'],r['method']) == (g['mode'],g['model'],g['method']))
    unified=[]
    for g in groups:
        f=fgroups[g['mode'],g['model'],g['method']]
        unified.append(dict(mode=g['mode'],model=g['model'],method=g['method'],planned_n=160,
                            answered_n=f['answered_n'],conditional_answered_n=f['conditional_answered_n'],
                            generation_failures=g['generation_failures'],
                            **{k:f[k+'_bounds'][0] for k in ('K','F','A')},
                            factor_scale=100,EAS_arith=g['EAS_arith'],EAS_geo=g['EAS_geo'],
                            EAS_arith_ci95=json.dumps(g['EAS_arith_ci95']),EAS_geo_ci95=json.dumps(g['EAS_geo_ci95']),
                            factor_denominator='answered/answered/conditional_answered',EAS_denominator=160))
    with (R/'tables/final_metrics.csv').open('w',encoding='utf-8-sig',newline='') as file:
        writer=csv.DictWriter(file,fieldnames=list(unified[0]));writer.writeheader();writer.writerows(unified)
    A.mkdir(parents=True, exist_ok=True)
    font = st.setup()
    figdir = R/'figures'

    def table(name, title, label, headers, body):
        text = [r'\begin{table}[htbp]\centering\footnotesize\setlength{\tabcolsep}{3pt}',
                r'\caption{'+title+r'}\label{'+label+'}',
                r'\begin{tabular}{l'+'r'*(len(headers)-1)+'}', r'\toprule',
                ' & '.join(headers)+r' \\ \midrule']
        text += [' & '.join(map(str, row))+r' \\' for row in body]
        text += [r'\bottomrule\end{tabular}\end{table}']
        (A/name).write_text('\n'.join(text)+'\n',encoding='utf-8')

    def interval(xs):
        return '['+', '.join(f'{x:.2f}' for x in xs)+']'

    headers=['方法','模型','EAS算术','算术95\%CI','EAS几何','成功/160']
    for name, label, title, selected in [
        ('final_agentic.tex','tab:ch2-agentic','九种Agentic方法的最终结果（每配置160题）',[g for g in groups if g['mode']=='agentic' and g['method'] in st.MAIN]),
        ('final_single_pass.tex','tab:ch2-sp','Single-Pass的最终结果（每配置160题）',[g for g in groups if g['mode']=='single_pass']),
        ('final_ablations.tex','tab:ch2-ablations','完整图与消融配置的最终结果（每配置160题）',[g for g in groups if g['mode']=='agentic' and g['method'] in ('graph','no_cross','no_aliases','no_traversal','anchor_only')])]:
        table(name,title,label,headers,[[st.NAMES[g['method']],g['model'].replace('qwen3-','').upper(),f"{g['EAS_arith']:.2f}",interval(g['EAS_arith_ci95']),f"{g['EAS_geo']:.2f}",g['successes']] for g in selected])
    table('final_mode_comparison.tex','Single-Pass减Agentic的最终配对结果（每项160题）','tab:ch2-modes',
          ['后端','模型','算术差','95\%CI','几何差','算术校正$p$'],
          [[st.NAMES[p['left_method']],p['model'].replace('qwen3-','').upper(),f"{p['difference']:.2f}",interval(p['ci95']),
            f"{next(q['difference'] for q in pairs if q['family']=='mode' and q['model']==p['model'] and q['left_method']==p['left_method'] and q['metric']=='EAS_geo'):.2f}",
            f"{p['holm_adjusted_p']:.6f}"] for p in pairs if p['family']=='mode' and p['metric']=='EAS_arith'])
    table('final_costs.tex','三个后端两模式的过程与已记录资源（每配置160题）','tab:ch2-costs',
          ['后端/模式','模型','工具采用/\%','平均动作','平均字符','已记录token/千'],
          [[st.NAMES[g['method']]+'/'+('单次' if g['mode']=='single_pass' else '自主'),g['model'].replace('qwen3-','').upper(),
            f"{g['tool_adoption_rate']*100:.2f}",f"{g['mean_tool_calls']:.2f}",f"{g['mean_characters']:.0f}",f"{(g['actual_prompt_tokens']+g['actual_completion_tokens'])/1000:.1f}"] for g in groups if g['method'] in ('graph','bm25','bge_m3')])
    fig, axes = plt.subplots(1,2,figsize=(7.1,3.7))
    for ax,model in zip(axes,('qwen3-8b','qwen3-14b')):
        for i,method in enumerate(st.MAIN):
            g=next(g for g in groups if (g['mode'],g['model'],g['method'])==('agentic',model,method))
            lo,hi=g['EAS_arith_ci95']
            ax.errorbar(g['EAS_arith'],i,xerr=[[g['EAS_arith']-lo],[hi-g['EAS_arith']]],fmt='o',color=st.COLORS[method],capsize=2)
        ax.set(yticks=range(9),yticklabels=[st.NAMES[m] for m in st.MAIN],xlim=(0,100),xlabel='EAS算术均值及95%置信区间（分）',title=model)
        ax.invert_yaxis();ax.grid(axis='x',alpha=.18)
    st.save(fig,figdir,'final_main_scores')
    fig,axes=plt.subplots(1,2,figsize=(7.1,3.9))
    for ax,model in zip(axes,('qwen3-8b','qwen3-14b')):
        mat=np.array([[np.mean([r['score']['composite']['EAS_arith'] for r in rows if (r['mode'],r['model'],r['method'],r['type'])==('agentic',model,m,t)]) for t in ('S0','S1','M0','M1')] for m in st.MAIN])
        im=ax.imshow(mat,cmap=st.CMAP,vmin=0,vmax=100,aspect='auto')
        for i in range(9):
            for j in range(4):ax.text(j,i,f'{mat[i,j]:.1f}',ha='center',va='center',fontsize=7,color='white' if mat[i,j]<15 or mat[i,j]>85 else '#222222')
        ax.set(yticks=range(9),yticklabels=[st.NAMES[m] for m in st.MAIN],xticks=range(4),xticklabels=['单非条件','单条件','多非条件','多条件'],title=model)
    fig.subplots_adjust(right=.87,wspace=.6);cax=fig.add_axes([.90,.18,.015,.65]);fig.colorbar(im,cax=cax).set_label('EAS算术均值（分）')
    for ext in ('pdf','svg','png'):fig.savefig(figdir/('final_type_scores.'+ext),dpi=300,bbox_inches='tight')
    plt.close(fig)
    for family,filename in [('ablation','final_ablation_differences'),('mode','final_mode_differences')]:
        fig,axes=plt.subplots(1,2,figsize=(7.1,2.8))
        for ax,model in zip(axes,('qwen3-8b','qwen3-14b')):
            own=[p for p in pairs if p['family']==family and p['model']==model and p['metric']=='EAS_arith']
            for i,p in enumerate(own):
                lo,hi=p['ci95'];ax.errorbar(p['difference'],i,xerr=[[p['difference']-lo],[hi-p['difference']]],fmt='o',color=st.COLORS[p['right_method'] if family=='ablation' else p['left_method']],capsize=2)
            ax.set(yticks=range(len(own)),yticklabels=[st.NAMES[p['right_method'] if family=='ablation' else p['left_method']] for p in own],xlabel='配对EAS算术差及95%置信区间（分）',title=model)
            ax.invert_yaxis();ax.axvline(0,color='#666666',lw=.7);ax.grid(axis='x',alpha=.18)
        st.save(fig,figdir,filename)
    # Evidence and adoption do not depend on ratings; their bound snapshot was
    # already validated against unchanged generations. Reuse their exact bytes.
    for stem in ('backend_evidence','tool_adoption'):
        for ext in ('pdf','svg','png'):
            shutil.copyfile(figdir/('draft_'+stem+'.'+ext),figdir/('final_'+stem+'.'+ext))
    for p in list(A.glob('draft_factor*')):
        shutil.copyfile(p,A/p.name.replace('draft_','final_',1))
    for p in figdir.glob('final_*.*'):
        shutil.copyfile(p,A/p.name)
    result=dict(status='final_assets_ready_for_manuscript_review',font=font,groups=32,answered=4989,dual_valid=4989,
                source_snapshot_sha256=s.sha(R/'manuscript_snapshot.json'),
                source_hashes={str(p.relative_to(s.WORKSPACE)):s.sha(p) for p in [R/'test160_results.json',R/'factor_analysis_provenance.json',Path(__file__),Path(st.__file__)]},
                outputs={str(p.relative_to(s.WORKSPACE)):s.sha(p) for p in A.glob('final_*')})
    s.save(R/'final_assets_provenance.json',result)
    return result


def prepare():
    # All guards run before overwriting the paper's statistical snapshot.
    closure_guard(read(s.RUN/'test160_runs/closure_audit.json'))
    import test160_report as report
    # Six never-sent local-estimate holds were explicitly reviewed by the owner.
    # Reconciliation checks their identical wire request via the epoch adapter;
    # the original report implementation and actual 32K parser remain unchanged.
    import test160_extra_recovery as epoch
    _, approved=epoch.allowed_authorization()
    epoch.APPROVED.update((p['judge'],p['sample_id']) for p in approved if p['hold_reason']=='input_budget_hold')
    report.recovery.request=epoch.request
    policy=read(s.RUN/'release/protocol/test160_analysis.json')
    before,_,_,_=report.load_rows(s.RUN/'release/protocol/test160_approval.json',policy)
    assert all(r['generation_failed'] or r['evaluation_complete'] for r in before)
    assert all(r['score']['unknown_items']==0 for r in before)
    report.run(s.RUN/'release/protocol/test160_approval.json')
    data=read(R/'test160_results.json')
    assert all(r['generation_failed'] or r['evaluation_complete'] for r in data['per_answer'])
    assert all(r['score']['unknown_items']==0 for r in data['per_answer'])
    snapshot=dict(status='audited_final_closed_statistical_snapshot',background_recovery_excluded=True,
                  generation_tasks=5120,answered=4989,dual_valid=4989,formal_failures=131,
                  statistical_source_hashes={str((R/'tables'/name).relative_to(s.WORKSPACE)):s.sha(R/'tables'/name) for name in ('per_answer.csv','comparison.csv','single_pass.csv','paired_comparisons.csv')},
                  calibration_source_hashes=read(R/'manuscript_snapshot.json')['calibration_source_hashes'],
                  closure_audit_sha256=s.sha(s.RUN/'test160_runs/closure_audit.json'),reason='All formal answers raw-validated under frozen dual scoring; final publication authorized by owner')
    s.save(R/'manuscript_snapshot.json',snapshot)
    import test160_factor_analysis as factors
    factors.main(final=True)
    result=build()
    s.save(s.RUN/'test160_runs/final_publication_ready.json',dict(
        utc=s.now(),state='awaiting_manuscript_sync_and_visual_review',final_data_and_assets_verified=True,
        official_pdf_updated=False,assets_provenance_sha256=s.sha(R/'final_assets_provenance.json'),
        next_step='Update all Chapter 2 K/F/A/EAS narrative, tables and figures from final_* assets; inspect rendered PDF and release main.pdf; never retain provisional claims or overwrite unrelated edits.'))
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--prepare',action='store_true');p.add_argument('--check',action='store_true');args=p.parse_args()
    if args.check:
        try:closure_guard(read(s.RUN/'test160_runs/closure_audit.json'));print('closure_ready')
        except RuntimeError as exc:print(str(exc));raise SystemExit(2)
    elif args.prepare:prepare()
    else:build()
