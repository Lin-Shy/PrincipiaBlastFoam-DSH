"""可重现阶段性图表。原始评分未闭合时绝不标为最终结果。"""
from pathlib import Path
import csv,json,hashlib,shutil,statistics,html,argparse
import numpy as np
import matplotlib.pyplot as plt
import figure_style as st
import single_pass_dev40 as s
from dev40_final_analysis import judged

R=s.RUN/'results'; T=R/'tables'; A=s.WORKSPACE/'graduation-thesis-materials/graduation-manuscript/assets/chapter2_test160'
def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def csvread(name):return list(csv.DictReader((T/name).open(encoding='utf-8-sig')))
def bounds(r,k='EAS_arith'):return json.loads(r[k+'_bounds'])
def label(r,k='EAS_arith'):
    lo,hi=bounds(r,k);return f'[{lo:.2f}, {hi:.2f}]'
def writecsv(name,rows):
    with (T/name).open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
def run(snapshot=False):
    audit=read(s.RUN/'test160_runs/closure_audit.json');assert audit['generation_tasks']==5120
    rows=csvread('per_answer.csv'); lookup={(r['mode'],r['model'],r['method'],r['question_id']):r for r in rows}
    assert len(lookup)==5120
    # Recompute all answer scores from canonical raw-validated judge records.
    snapshot_sources={}
    if snapshot:
        prior=read(R/'draft_assets_provenance.json')
        for path,digest in prior['source_hashes'].items():
            p=Path(path)
            if p.name in ['per_answer.csv','comparison.csv','single_pass.csv','paired_comparisons.csv']:
                assert sha(s.WORKSPACE/p)==digest,'Statistical snapshot changed: '+path
                snapshot_sources[path]=digest
        assert len(snapshot_sources)==4
    for mode,base in ([] if snapshot else [('agentic',s.RUN/'test160_runs'),('single_pass',s.RUN/'test160_runs/supplement/single_pass')]):
        for p in read(base/'scoring/packet.json')['items']:
            r=lookup[(mode,p['model'],p['method'],p['qid'])];score=judged(base/'scoring',p['item'],p['item']['generation_failed'])
            assert r['source_sha256']==p['generation_sha256']
            for k in ['EAS_arith','EAS_geo']:
                assert np.allclose(bounds(r,k),score['bounds'][k])
                x=score['composite'][k];assert (not r[k]) if x is None else abs(float(r[k])-x)<1e-8
    groups=csvread('comparison.csv')+csvread('single_pass.csv')
    for g in groups:
        own=[r for r in rows if all(r[k]==g[k] for k in ['mode','model','method'])];assert len(own)==160
        for k in ['EAS_arith','EAS_geo']:assert np.allclose(bounds(g,k),np.mean([bounds(r,k) for r in own],axis=0))
    # Compact table uses actual missing-answer counts, never criterion missing_items.
    brief=[]
    for g in groups:
        own=[r for r in rows if all(r[k]==g[k] for k in ['mode','model','method'])]
        brief.append(dict(mode=g['mode'],model=g['model'],method=g['method'],EAS_arith=label(g),EAS_geo=label(g,'EAS_geo'),answered=int(g['successes']),dual_valid_answered=sum(r['generation_failed']=='False' and r['evaluation_complete']=='True' for r in own),missing_dual=sum(r['generation_failed']=='False' and r['evaluation_complete']!='True' for r in own),success_rate=g['success_rate'],tool_adoption_rate=g['tool_adoption_rate'],mean_tool_calls=g['mean_tool_calls'],mean_characters=g['mean_characters'],prompt_tokens=g['actual_prompt_tokens'],completion_tokens=g['actual_completion_tokens']))
    writecsv('draft_scorecard.csv',brief)
    font=st.setup();figdir=R/'figures'; models=['qwen3-8b','qwen3-14b']
    fig,axes=plt.subplots(1,2,figsize=(7.1,3.7))
    for ax,m in zip(axes,models):
        for i,method in enumerate(st.MAIN):
            g=next(g for g in groups if (g['mode'],g['model'],g['method'])==('agentic',m,method));lo,hi=bounds(g)
            ax.plot([lo,hi],[i,i],color=st.COLORS[method],lw=2);ax.plot([lo,hi],[i,i],'|',color=st.COLORS[method]);
        states={g['method']:('完成' if int(g['evaluation_complete'])==160 else '待补') for g in groups if g['mode']=='agentic' and g['model']==m}
        ax.set(yticks=range(9),yticklabels=[st.NAMES[x]+'（'+states[x]+'）' for x in st.MAIN],xlim=(0,100),xlabel='EAS算术下界至上界（分）',title=m.replace('qwen3-','Qwen3-')+'：统一识别边界');ax.invert_yaxis();ax.grid(axis='x',alpha=.18)
    st.save(fig,figdir,'draft_main_bounds')
    fig,axes=plt.subplots(2,2,figsize=(7.1,6.9),layout='constrained')
    im=None
    for model_index,model in enumerate(models):
        limits=np.zeros((9,4,2))
        for i,method in enumerate(st.MAIN):
            for j,ty in enumerate(['S0','S1','M0','M1']):
                own=[r for r in rows if (r['mode'],r['model'],r['method'],r['type'])==('agentic',model,method,ty)];assert len(own)==40
                lo,hi=np.mean([bounds(r) for r in own],axis=0)
                limits[i,j]=[lo,hi]
        for side,ax in enumerate(axes[model_index]):
            mat=limits[:,:,side];im=ax.imshow(mat,cmap=st.CMAP,vmin=0,vmax=100,aspect='auto')
            for i in range(9):
                for j in range(4):ax.text(j,i,f'{mat[i,j]:.1f}',ha='center',va='center',fontsize=st.HEATMAP_NUM_SIZE,color='white' if mat[i,j]<15 or mat[i,j]>85 else '#222222')
            ax.set(title=model+'：'+['下界','上界'][side],xticks=range(4),xticklabels=['单非条件','单条件','多非条件','多条件'],yticks=range(9),yticklabels=[st.NAMES[x] for x in st.MAIN]);ax.tick_params(axis='x',labelsize=st.HEATMAP_AXIS_SIZE)
    fig.colorbar(im,ax=list(axes.flat),pad=.02,shrink=.8).set_label('EAS算术识别界限（分）')
    # constrained layout handles the shared colorbar; do not apply tight_layout.
    for ext in ['pdf','svg','png']:fig.savefig(figdir/('draft_type_scores.'+ext),dpi=300,bbox_inches='tight')
    plt.close(fig)
    # Backend evidence heatmap uses directly observed evidence, independent of missing grades.
    fig,ax=plt.subplots(figsize=(6.8,2.7));mat=[]
    for method in ['graph','bm25','bge_m3']:
        vals=[]
        for ty in ['S0','S1','M0','M1']:
            own=[r for r in rows if r['mode']=='single_pass' and r['model']=='qwen3-14b' and r['method']==method and r['type']==ty];assert len(own)==40
            vals.append(statistics.mean(float(r['line_recall']) for r in own)*100)
        mat.append(vals)
    im=ax.imshow(mat,cmap=st.CMAP,vmin=0,vmax=100,aspect='auto');ax.set(xticks=range(4),xticklabels=['单资料非条件','单资料条件','多资料非条件','多资料条件'],yticks=range(3),yticklabels=[st.NAMES[x] for x in ['graph','bm25','bge_m3']])
    for i in range(3):
        for j in range(4):ax.text(j,i,f'{mat[i][j]:.1f}',ha='center',va='center',color='white' if mat[i][j]<20 or mat[i][j]>80 else '#222222')
    fig.colorbar(im,ax=ax,pad=.03).set_label('必要原文行召回率（%）');st.save(fig,figdir,'draft_backend_evidence')
    paired=csvread('paired_comparisons.csv')
    for p in paired:
        for q in {r['question_id'] for r in rows}:assert (p['left_mode'],p['model'],p['left_method'],q) in lookup and (p['right_mode'],p['model'],p['right_method'],q) in lookup
        diffs=[]
        for q in sorted({r['question_id'] for r in rows}):
            a=bounds(lookup[p['left_mode'],p['model'],p['left_method'],q],p['metric']);b=bounds(lookup[p['right_mode'],p['model'],p['right_method'],q],p['metric']);diffs.append([a[0]-b[1],a[1]-b[0]])
        assert np.allclose(np.mean(diffs,axis=0),json.loads(p['bounds']))
    for family,name in [('ablation','draft_ablation_bounds'),('mode','draft_mode_bounds')]:
        fig,axes=plt.subplots(1,2,figsize=(7.1,2.8))
        for ax,m in zip(axes,models):
            own=[r for r in paired if r['family']==family and r['model']==m and r['metric']=='EAS_arith']
            for i,r in enumerate(own):
                lo,hi=json.loads(r['bounds']);ax.plot([lo,hi],[i,i],color=st.COLORS[r['right_method'] if family=='ablation' else r['left_method']],lw=2);ax.plot([lo,hi],[i,i],'|',color='#333333')
            ax.set(yticks=range(len(own)),yticklabels=[st.NAMES[r['right_method'] if family=='ablation' else r['left_method']] for r in own],title=m,xlim=(-100,100),xlabel=('完整图减消融' if family=='ablation' else 'Single-Pass减Agentic')+'（分）');ax.invert_yaxis();ax.axvline(0,color='#666666',lw=.7);ax.grid(axis='x',alpha=.18)
        st.save(fig,figdir,name)
    fig,ax=plt.subplots(figsize=(6.8,2.4));x=np.arange(3);width=.32
    for i,m in enumerate(models):
        own=[next(g for g in groups if (g['mode'],g['model'],g['method'])==('agentic',m,method)) for method in ['graph','bm25','bge_m3']]
        ax.bar(x+(i-.5)*width,[100*float(g['tool_adoption_rate']) for g in own],width,color=plt.get_cmap('coolwarm')([.12,.88][i]),label=m)
    ax.set(xticks=x,xticklabels=[st.NAMES[x] for x in ['graph','bm25','bge_m3']],ylabel='至少调用一次工具（%）',ylim=(0,105));ax.legend(loc='upper center',bbox_to_anchor=(.5,1.2),ncol=2);ax.grid(axis='y',alpha=.18);st.save(fig,figdir,'draft_tool_adoption')
    A.mkdir(exist_ok=True,parents=True)
    for p in figdir.glob('draft_*.*'):shutil.copyfile(p,A/p.name)
    lines=[r'\begingroup\footnotesize\setlength{\tabcolsep}{3pt}',r'\begin{longtable}{llrrrr}',r'\caption{Test160阶段性评分：固定160题分母，方括号为识别边界}\label{tab:ch2-test160-scorecard}\\',r'\toprule 方法 & 模型 & EAS算术 & EAS几何 & 有效回答 & 双评缺口 \\ \midrule\endfirsthead',r'\toprule 方法 & 模型 & EAS算术 & EAS几何 & 有效回答 & 双评缺口 \\ \midrule\endhead']
    for g in brief:
        lines.append(st.NAMES[g['method']]+('（单次）' if g['mode']=='single_pass' else '')+' & '+g['model'].replace('qwen3-','')+' & '+g['EAS_arith']+' & '+g['EAS_geo']+' & '+str(g['answered'])+' & '+str(g['missing_dual'])+r' \\')
    lines += [r'\bottomrule\end{longtable}\endgroup'];(A/'draft_scorecard.tex').write_text('\n'.join(lines),encoding='utf-8')
    def table(name,title,tag,headers,body):
        lines=[r'\begin{table}[htbp]\centering\footnotesize\setlength{\tabcolsep}{3pt}',r'\caption{'+title+r'}\label{'+tag+'}',r'\begin{tabular}{l'+'r'*(len(headers)-1)+'}',r'\toprule',' & '.join(headers)+r' \\ \midrule']
        lines+=[' & '.join(map(str,row))+r' \\' for row in body]
        lines += [r'\bottomrule\end{tabular}\end{table}']
        (A/name).write_text('\n'.join(lines)+'\n',encoding='utf-8')
    headers=['方法','模型','EAS算术$[L,U]$','EAS几何$[L,U]$','双评缺口','状态']
    for name,title,tag,selected in [
       ('draft_single_pass.tex','Single-Pass RAG结果：每配置160题，统一报告缺评识别边界','tab:ch2-sp', [g for g in brief if g['mode']=='single_pass']),
       ('draft_agentic.tex','Agentic RAG九种主方法：每配置160题，统一报告缺评识别边界','tab:ch2-agentic',[g for g in brief if g['mode']=='agentic' and g['method'] in st.MAIN]),
       ('draft_ablations.tex','完整来源图及四项消融：每配置160题，统一报告缺评识别边界','tab:ch2-ablations',[g for g in brief if g['mode']=='agentic' and g['method'] in ['graph','no_cross','no_aliases','no_traversal','anchor_only']])]:
        table(name,title,tag,headers,[[st.NAMES[g['method']],g['model'].replace('qwen3-',''),g['EAS_arith'],g['EAS_geo'],g['missing_dual'],'完成' if g['missing_dual']==0 else '待补'] for g in selected])
    table('draft_mode_comparison.tex','Single-Pass减Agentic的同题得分差：统一报告识别边界','tab:ch2-modes',['后端','模型','EAS算术差$[L,U]$','EAS几何差$[L,U]$'],[
       [st.NAMES[method],model.replace('qwen3-','')]+['['+', '.join(f'{x:.2f}' for x in json.loads(next(p['bounds'] for p in paired if p['family']=='mode' and p['model']==model and p['left_method']==method and p['metric']==metric)))+']' for metric in ['EAS_arith','EAS_geo']]
       for model in models for method in ['graph','bm25','bge_m3']])
    costs=[g for g in groups if g['method'] in ['graph','bm25','bge_m3']]
    table('draft_costs.tex','三个后端两种模式的过程与已记录资源（每配置160题）','tab:ch2-costs',['后端/模式','模型','工具采用/\%','平均动作','平均字符','已记录token/千'],[
       [st.NAMES[g['method']]+'/'+('单次' if g['mode']=='single_pass' else '自主'),g['model'].replace('qwen3-',''),f"{float(g['tool_adoption_rate'])*100:.2f}",f"{float(g['mean_tool_calls']):.2f}",f"{float(g['mean_characters']):.0f}",f"{(float(g['actual_prompt_tokens'])+float(g['actual_completion_tokens']))/1000:.1f}"] for g in costs])
    files=[T/'per_answer.csv',T/'comparison.csv',T/'single_pass.csv',T/'paired_comparisons.csv',T/'draft_scorecard.csv',R/'manuscript_snapshot.json' if snapshot else s.RUN/'test160_runs/closure_audit.json',Path(__file__),Path(st.__file__)]
    report=dict(status='provisional_unclosed',font=font,answers_recomputed=5120 if not snapshot else 'Previously recomputed audited snapshot; current worker output deliberately excluded',groups_checked=32,uniform_missing_bounds=True,snapshot_mode=snapshot,prior_verified_statistical_sources=snapshot_sources,source_hashes={str(p.relative_to(s.WORKSPACE)):sha(p) for p in files},output_hashes={str(p.relative_to(s.WORKSPACE)):sha(p) for p in A.glob('draft_*')})
    s.save(R/'draft_assets_provenance.json',report)
    body='<html lang="zh-CN"><meta charset="utf-8"><title>Test160未闭合结果草稿</title><body><h1>Test160：评分未闭合</h1><p>5120生成终态，4989有效回答，2322双评完成，2667缺双评；131正式失败保留。识别边界不是95%置信区间。</p><p><a href="tables/closure_audit.csv">逐任务审计</a> · <a href="tables/draft_scorecard.csv">32配置得分与缺口</a> · <a href="tables/per_answer.csv">逐题数据</a> · <a href="tables/paired_comparisons.csv">配对统计及边界</a></p>'
    for name in ['draft_backend_evidence','draft_main_bounds','draft_type_scores','draft_ablation_bounds','draft_mode_bounds','draft_tool_adoption']:body+=f'<p><img style="max-width:100%" src="figures/{name}.svg" alt="{name}"></p>'
    (R/'draft.html').write_text(body+'</body></html>',encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--snapshot',action='store_true',help='Re-layout the previously audited, hash-verified statistical snapshot while recovery is running');run(p.parse_args().snapshot)
