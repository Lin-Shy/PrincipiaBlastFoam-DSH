"""Paired cluster inference for the preregistered objective experiment."""
import numpy as np
def holm(values):
    order=np.argsort(values);out=[0.0]*len(values);floor=0.0
    for rank,i in enumerate(order):
        floor=max(floor,min(1.0,float(values[i])*(len(values)-rank)));out[int(i)]=floor
    return out

def analyze(rows,protocol):
    clusters=sorted({r['cluster'] for r in rows});configs=sorted({r['config_id'] for r in rows})
    rng=np.random.default_rng(protocol['seed']);n=len(clusters)
    draws=rng.integers(0,n,size=(protocol['bootstrap_samples'],n))
    sums={};counts={};meta={}
    for config in configs:
        rs=[r for r in rows if r['config_id']==config];meta[config]=rs[0]
        sums[config]=np.array([sum(r['score'] for r in rs if r['cluster']==cl) for cl in clusters],dtype=float)
        counts[config]=np.array([sum(r['cluster']==cl for r in rs) for cl in clusters],dtype=float)
    intervals={}
    for c in configs:
        sample=sums[c][draws].sum(axis=1)/counts[c][draws].sum(axis=1)
        intervals[c]=np.quantile(sample,[.025,.975]).tolist()
    if n<=20:
        signs=1-2*((np.arange(2**n,dtype=np.uint32)[:,None]>>np.arange(n,dtype=np.uint32))&1).astype(np.int8)
    else:signs=rng.choice([-1,1],size=(100000,n)).astype(np.int8)
    pairs=[]
    for model in sorted({r['model'] for r in rows}):
        cs=[c for c in configs if meta[c]['model']==model];graph=next(c for c in cs if meta[c]['method']=='graph')
        for c in cs:
            if c==graph:continue
            assert np.array_equal(counts[c],counts[graph])
            delta=sums[graph]-sums[c];obs=float(delta.sum()/counts[c].sum())
            boots=delta[draws].sum(axis=1)/counts[c][draws].sum(axis=1)
            exceed=int(np.count_nonzero(np.abs(signs@delta)>=abs(delta.sum())-1e-12))
            p=exceed/len(signs) if n<=20 else (exceed+1)/(len(signs)+1)
            family='ablation' if meta[c]['method'] in ('no_cross','no_aliases','no_traversal','anchor_only') else 'main'
            pairs.append(dict(model=model,reference='graph',comparison=meta[c]['method'],family=family,difference=obs,ci95=np.quantile(boots,[.025,.975]).tolist(),p=p))
    for family in ('main','ablation'):
        subset=[p for p in pairs if p['family']==family]
        assert len(subset)==protocol['families'][family]
        for p,adjusted in zip(subset,holm([p['p'] for p in subset])):p['holm_p']=adjusted
    return dict(clusters=n,cluster_ids=clusters,ci95=intervals,paired=pairs,seed=protocol['seed'],bootstrap_samples=protocol['bootstrap_samples'])
