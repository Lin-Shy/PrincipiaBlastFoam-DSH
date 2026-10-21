"""标准matplotlib绘图；只从真实已完成的离线评价取数。"""
import argparse
from common import *

def main(source,output):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    source=ARCHIVE/'evaluation'/source/'summary.json';data=read(source)
    out=ARCHIVE/'figures'/output;out.mkdir(parents=True,exist_ok=False)
    methods=sorted({r['method'] for r in data['overall']})
    for metric,title in [('evidence_recall','Complete registered evidence recall'),('all_evidence','All registered evidence acquired')]:
        fig,ax=plt.subplots(figsize=(8,5))
        for m in methods:
            rs=sorted([r for r in data['overall'] if r['method']==m],key=lambda r:r['budget'])
            ax.plot([r['budget'] for r in rs],[100*r[metric] for r in rs],marker='o',label=m)
        ax.set(xlabel='Serialized response budget (characters)',ylabel=title+' (%)',xticks=[2000,4000,6000],ylim=(0,100))
        ax.grid(alpha=.2);ax.legend(fontsize=8,ncol=2);fig.tight_layout()
        for ext in ['png','pdf']:fig.savefig(out/(metric+'.'+ext),dpi=200)
        plt.close(fig)
    fig,axes=plt.subplots(1,4,figsize=(14,4),sharey=True)
    types=sorted({r['type'] for r in data['by_type']})
    for ax,t in zip(axes,types):
        rs=[r for r in data['by_type'] if r['budget']==6000 and r['type']==t]
        ax.bar([r['method'] for r in rs],[100*r['evidence_recall'] for r in rs])
        ax.set_title(t);ax.tick_params(axis='x',labelrotation=80,labelsize=8);ax.set_ylim(0,100)
    axes[0].set_ylabel('Registered evidence recall (%)');fig.tight_layout()
    for ext in ['png','pdf']:fig.savefig(out/('types_6000.'+ext),dpi=200)
    plt.close(fig)
    save(out/'manifest.json',dict(source_sha256=sha(source),script_sha256=sha(Path(__file__)),files={p.name:sha(p) for p in out.iterdir()}))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();main(a.source,a.output)
