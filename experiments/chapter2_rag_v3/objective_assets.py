"""Generate objective-result manuscript assets from a closed snapshot only."""
import json
from pathlib import Path
import matplotlib.pyplot as plt
import figure_style as style
import objective_experiment as experiment

def main():
    path=experiment.OUT/'results/snapshot.json'
    snap=experiment.read(path)
    if snap['status']!='closed' or snap['completed']!=snap['planned']:
        raise ValueError('objective experiment must be closed before producing manuscript assets')
    stats=snap['statistics']; rows=snap['configurations']; style.setup()
    fig,axes=plt.subplots(1,2,figsize=(7.2,4.1),sharey=True)
    for ax,model in zip(axes,('qwen3-8b','qwen3-14b')):
        entries=[next(r for r in rows if r['model']==model and r['method']==method) for method in style.MAIN]
        for i,r in enumerate(entries):
            lo,hi=stats['ci95'][r['config_id']]; mean=r['accuracy']
            ax.plot([100*lo,100*hi],[i,i],color=style.MODEL_COLORS[model])
            ax.plot(100*mean,i,'o',color=style.MODEL_COLORS[model])
        ax.set_yticks(range(len(entries)),[style.NAMES[r['method']] for r in entries])
        ax.invert_yaxis();ax.set_xlim(0,100);ax.set_title(model);ax.set_xlabel('客观题准确率（%）')
    style.save(fig,experiment.OUT/'results/figures','objective_main_accuracy')
    assets=experiment.WORK/'graduation-thesis-materials/graduation-manuscript/assets'
    assets.mkdir(parents=True,exist_ok=True)
    import shutil
    shutil.copyfile(experiment.OUT/'results/figures/objective_main_accuracy.pdf',assets/'objective_main_accuracy.pdf')
    lines=[r'\begin{table}[htbp]\centering\footnotesize',r'\caption{客观题准确率及题型分项（每配置固定分母）}\label{tab:ch2-objective}',r'\begin{tabular}{llrrrrrr}\toprule',r'模型 & 方法 & 完成 & 总体 & 填空 & 短答 & 单选 & 判断 \\ \midrule']
    for model in ('qwen3-8b','qwen3-14b'):
        for method in style.NAMES:
            r=next(x for x in rows if x['model']==model and x['method']==method)
            nums=[r['accuracy'],r['fill_accuracy'],r['short_accuracy'],r['single_accuracy'],r['judge_accuracy']]
            lines.append(model.replace('-','\\mbox{-}')+' & '+style.NAMES[method]+' & '+str(r['completed'])+'/'+str(r['planned'])+' & '+' & '.join(f'{x*100:.1f}' for x in nums)+r' \\')
    lines.extend([r'\bottomrule\end{tabular}',r'\end{table}'])
    (assets/'objective_metrics.tex').write_text('\n'.join(lines)+'\n',encoding='utf-8',newline='\n')
    experiment.save(experiment.OUT/'results/objective_assets_provenance.json',dict(snapshot_sha256=experiment.sha(path),
        figure_sha256=experiment.sha(assets/'objective_main_accuracy.pdf'),table_sha256=experiment.sha(assets/'objective_metrics.tex'),
        source_sha256=experiment.sha(Path(__file__))))
    print('objective manuscript assets generated')

if __name__=='__main__':main()
