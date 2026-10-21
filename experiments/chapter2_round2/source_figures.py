"""从真实节点、边和交付轨迹生成局部结构和来源追踪草图。"""
from common import *

def main(run_id,output):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from textwrap import wrap
    graph=read(GRAPH);edges={e['id']:e for e in graph['edges']}
    chosen=None
    for q in sorted(public_questions(),key=lambda q:q['id']):
        path=ARCHIVE/'runs'/run_id/'graph/traces'/(q['id']+'.json');t=read(path)
        ids=[]
        for row in t['ranking']['items'][:10]:
            ids += [step['edge_id'] for step in row['route'] if step['edge_id'] in edges]
        ids=list(dict.fromkeys(ids))[:5]
        if ids:chosen=(q,t,path,ids);break
    if chosen is None:raise ValueError('no real routed example; do not invent one')
    q,t,path,ids=chosen
    actual_edges=[edges[k] for k in ids]
    node_ids=list(dict.fromkeys(n for e in actual_edges for n in [e['source'],e['target']]))
    actual_nodes={n:graph['nodes'][n] for n in node_ids}
    out=ARCHIVE/'figures'/output;out.mkdir(parents=True,exist_ok=False)
    save(out/'source_data.json',dict(question=q,graph_sha256=sha(GRAPH),trace_sha256=sha(path),
         node_ids=node_ids,nodes=actual_nodes,edges=actual_edges,selection='first public id with top10 actual relation routes; at most first5 distinct route edges',
         interpretation='source organization and literal graph routes; not entailment or simulation validation'))
    # Stable two-column source diagram; every arrow is a real directed edge.
    sources=list(dict.fromkeys(e['source'] for e in actual_edges))
    targets=[n for n in node_ids if n not in sources]
    if not targets:targets=node_ids[len(node_ids)//2:];sources=node_ids[:len(node_ids)//2]
    positions={n:(.18,1-(i+1)/(len(sources)+1)) for i,n in enumerate(sources)}
    positions.update({n:(.8,1-(i+1)/(len(targets)+1)) for i,n in enumerate(targets)})
    fig,ax=plt.subplots(figsize=(11,6));ax.set_xlim(0,1);ax.set_ylim(0,1);ax.axis('off')
    for n,(x,y) in positions.items():
        node=actual_nodes[n];u=graph['units'][node['unit_id']]
        text='\n'.join(wrap(node['path'],width=45,break_long_words=True,break_on_hyphens=False))+f"\nL{u['start']}-{u['end']} | {node['kind']}\nID ...{n[-12:]}"
        ax.text(x,y,text,ha='center',va='center',fontsize=7,bbox=dict(boxstyle='round,pad=.6',fc='#e8f0fb',ec='#6a7fa1'))
    for i,e in enumerate(actual_edges):
        a=positions[e['source']];b=positions[e['target']]
        ax.annotate('',xy=b,xytext=a,arrowprops=dict(arrowstyle='->',color='#677c9a',connectionstyle=f'arc3,rad={.10*(i%3-1)}',shrinkA=40,shrinkB=40))
        ax.text((a[0]+b[0])/2,(a[1]+b[1])/2+.02*(i%3-1),e['relation'],fontsize=7,ha='center',bbox=dict(fc='white',ec='none',alpha=.85))
    ax.set_title('Observed source graph routes | '+q['id'],fontsize=12)
    fig.tight_layout()
    for ext in ['png','pdf']:fig.savefig(out/('local_graph.'+ext),dpi=200)
    plt.close(fig)
    fig,ax=plt.subplots(figsize=(11,5));ax.axis('off')
    slots=t['selected_slots'][:5]
    ax.text(.03,.88,q['id']+' | unchanged public query',fontsize=12,bbox=dict(fc='#e8f0fb',ec='none',pad=12))
    for i,s in enumerate(slots):
        y=.65-i*.13
        ax.text(.18,y,f"slot {i+1}   "+s['path']+f" : L{s['start']}-{s['end']}",fontsize=9,
                bbox=dict(fc='#edf5ef',ec='none',pad=8))
        ax.annotate('',xy=(.16,y),xytext=(.08,.8),arrowprops=dict(arrowstyle='->',color='#6b8871'))
    ax.text(.03,.04,'Actual full-graph source slots before 2000/4000/6000-character delivery; no QA generation in this experiment.',fontsize=8)
    fig.tight_layout()
    for ext in ['png','pdf']:fig.savefig(out/('source_trace.'+ext),dpi=200)
    plt.close(fig)
    save(out/'manifest.json',dict(script_sha256=sha(Path(__file__)),source_sha256=sha(out/'source_data.json'),
                                files={p.name:sha(p) for p in out.iterdir() if p.suffix in ['.png','.pdf']}))
    print('source figure question',q['id'],'real edges',len(ids))

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--run-id',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    main(a.run_id,a.output)
