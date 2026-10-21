"""供正文草稿使用的分组图；完整十一方法保留在原结果表和附图。"""
from common import *

def main():
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    source=ARCHIVE/'evaluation/final_001/summary.json';s=read(source)
    out=ARCHIVE/'figures/reviewed_001';out.mkdir(parents=True,exist_ok=False)
    main=['graph','bm25','bge_m3','bm25_bge_m3','bm25_parent']
    ablations=['graph','no_traversal','anchor_only','no_cross','no_aliases']
    names=dict(graph='Full graph',bm25='BM25',bge_m3='BGE-M3 Dense',bm25_bge_m3='BM25 + BGE-M3',bm25_parent='BM25 + parent',
               no_traversal='No relation traversal',anchor_only='Anchor only',no_cross='No source association',no_aliases='No Chinese aliases')
    colors=dict(zip(set(main+ablations),plt.get_cmap('tab10').colors))
    # Fixed map, independent of hash/set iteration and measured scores.
    colors={m:plt.get_cmap('tab10')(i) for i,m in enumerate(dict.fromkeys(main+ablations))}
    for label,methods in [('text_baselines',main),('graph_ablations',ablations)]:
        fig,axes=plt.subplots(1,2,figsize=(11,4.1),sharex=True,sharey=True)
        for ax,metric,title in zip(axes,['evidence_recall','all_evidence'],['Registered evidence recall','All registered evidence acquired']):
            for i,m in enumerate(methods):
                rs=sorted([r for r in s['overall'] if r['method']==m],key=lambda r:r['budget'])
                ax.plot([r['budget'] for r in rs],[100*r[metric] for r in rs],marker=['o','s','^','D','v'][i],
                        color=colors[m],label=names[m],linewidth=1.8)
            ax.set(title=title,xlabel='Serialized budget (characters)',xticks=[2000,4000,6000],ylim=(0,100))
            ax.grid(alpha=.2)
        axes[0].set_ylabel('Coverage (%)');axes[1].legend(loc='upper left',fontsize=8)
        fig.tight_layout()
        for ext in ['png','pdf']:fig.savefig(out/(label+'.'+ext),dpi=220)
        plt.close(fig)
    types=[('single_False','Single source / no condition'),('single_True','Single source / condition'),
           ('multiple_False','Multiple sources / no condition'),('multiple_True','Multiple sources / condition')]
    fig,axes=plt.subplots(2,2,figsize=(10,7),sharey=True)
    short=['Graph','BM25','BGE-M3','Hybrid','Parent']
    for ax,(t,title) in zip(axes.flat,types):
        values=[next(r['evidence_recall']*100 for r in s['by_type'] if r['method']==m and r['budget']==6000 and r['type']==t) for m in main]
        bars=ax.bar(short,values,color=[colors[m] for m in main])
        ax.bar_label(bars,fmt='%.1f',fontsize=8,padding=2)
        ax.set(title=title,ylim=(0,100),ylabel='Registered evidence recall (%)')
        ax.grid(axis='y',alpha=.2)
    fig.suptitle('Fixed query, 6000 serialized characters; n=50 per type',fontsize=11)
    fig.tight_layout()
    for ext in ['png','pdf']:fig.savefig(out/('four_types.'+ext),dpi=220)
    plt.close(fig)
    save(out/'manifest.json',dict(input_sha256=sha(source),script_sha256=sha(Path(__file__)),
        chosen_groups='predefined RQ1 text baselines and separate graph ablations; all11 results remain in evaluation/final_001',
        files={p.name:sha(p) for p in out.iterdir()}))

if __name__=='__main__':main()
