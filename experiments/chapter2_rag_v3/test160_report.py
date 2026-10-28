"""Final, offline Test160 analysis. Refuses incomplete generation/scoring queues."""
import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime
import html
import itertools
import json
import math
from pathlib import Path
import shutil
import statistics

import numpy as np
import single_pass_dev40 as s
import test160_evaluation as evaluation
import dev40_finalize as recovery
from dev40_final_analysis import judged, evidence, number
from judge_statistics import ordinal_agreement

BASE=s.RUN/'test160_runs'
OUT=s.RUN/'results'
METHODS=['graph','bm25','e5','bge_m3','bm25_e5','bm25_bge_m3','bm25_parent','basic','direct','no_cross','no_aliases','no_traversal','anchor_only']
MODELS=['qwen3-8b','qwen3-14b']
METRICS=['EAS_arith','EAS_geo']
SHORT={'graph':'Source graph','bm25':'BM25','e5':'E5','bge_m3':'BGE-M3','bm25_e5':'BM25+E5','bm25_bge_m3':'BM25+BGE-M3','bm25_parent':'BM25 parent','basic':'Basic search','direct':'Direct','no_cross':'No source links','no_aliases':'No CN aliases','no_traversal':'No traversal','anchor_only':'Anchors only'}


def avg(values):
    return statistics.mean(values) if values and all(type(v) in (int,float) and math.isfinite(v) for v in values) else None


def csv_file(path, rows):
    rows=list(rows)
    keys=list(dict.fromkeys(k for r in rows for k in r))
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=keys);w.writeheader()
        for row in rows:
            w.writerow({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(list,dict,tuple)) else v for k,v in row.items()})


def clusters(annotations, units):
    parent={q:q for q in annotations}
    def find(q):
        while parent[q]!=q:
            parent[q]=parent[parent[q]];q=parent[q]
        return q
    def join(qs):
        qs=[q for q in qs if q in parent]
        for q in qs[1:]:parent[find(q)]=find(qs[0])
    for unit in units:join(unit['question_ids'])
    fact={q:find(q) for q in parent}
    for key in ('theme_id','split_group'):
        grouped=defaultdict(list)
        for q,a in annotations.items():grouped[a[key]].append(q)
        for qs in grouped.values():join(qs)
    return dict(fact=fact,linked={q:find(q) for q in parent},
                theme={q:a['theme_id'] for q,a in annotations.items()},
                knowledge={q:a['split_group'] for q,a in annotations.items()})


def bootstrap(bounds, ids, mapping, resamples=10000, seed=20261021, point_identified=None):
    """Ratio cluster bootstrap of question means; unknowns give an envelope."""
    if len(bounds)!=len(ids) or not ids:raise ValueError('Paired nonempty bounds required')
    groups=sorted({mapping[q] for q in ids})
    positions={g:i for i,g in enumerate(groups)}
    totals=np.zeros((len(groups),2));counts=np.zeros(len(groups))
    for q,(lo,hi) in zip(ids,bounds):
        if not math.isfinite(lo) or not math.isfinite(hi) or lo>hi:raise ValueError('Invalid bounds')
        i=positions[mapping[q]];totals[i]+=[lo,hi];counts[i]+=1
    rng=np.random.default_rng(seed)
    draw=rng.integers(0,len(groups),size=(resamples,len(groups)))
    samples=totals[draw].sum(axis=1)/counts[draw].sum(axis=1)[:,None]
    identified=all(lo==hi for lo,hi in bounds) if point_identified is None else point_identified
    return dict(questions=len(ids),clusters=len(groups),mean=avg([lo for lo,hi in bounds]) if identified else None,
                bounds=[sum(x[j] for x in bounds)/len(bounds) for j in (0,1)],
                ci95=[float(np.quantile(samples[:,0],.025)),float(np.quantile(samples[:,0],.975))] if identified else None,
                identification_envelope95=[float(np.quantile(samples[:,0],.025)),float(np.quantile(samples[:,1],.975))],
                equal_cluster_macro_bounds=(totals/counts[:,None]).mean(axis=0).tolist(),
                resamples=resamples,seed=seed,unit='linked clusters; question-weighted ratio estimator')


def signflip(differences, ids, mapping, two_sided=False):
    grouped=defaultdict(float)
    for q,d in zip(ids,differences):grouped[mapping[q]]+=d
    ds=np.array([v for v in grouped.values() if abs(v)>1e-12])
    if len(ds)>20:raise ValueError('More than 20 nonzero linked clusters: no silent test substitution')
    observed=float(ds.sum())
    sums=np.zeros(1)
    for d in ds:sums=np.concatenate([sums+d,sums-d])
    p=float(np.mean(np.abs(sums)>=abs(observed)-1e-10) if two_sided else np.mean(sums>=observed-1e-10))
    return dict(p=p,permutations=len(sums),nonzero_clusters=len(ds),two_sided=two_sided,
                assumption='Independent linked clusters with sign-exchangeable total paired effects; question pairing preserved')


def holm(rows):
    ordered=sorted(enumerate(rows),key=lambda z:1 if z[1]['p'] is None else z[1]['p'])
    last=0
    for rank,(i,row) in enumerate(ordered):
        last=max(last,min(1,(len(rows)-rank)*(1 if row['p'] is None else row['p'])))
        row.update(holm_adjusted_p=last if row['p'] is not None else None,
                   reject=bool(row['p'] is not None and last<=.05),planned_family_size=len(rows))


def load_rows(authorization, policy):
    manifest,questions=evaluation.authorize(authorization,'single_pass')
    annotations={a['id']:a for a in s.load(s.WORKSPACE/manifest['scoring_only']['annotations'])}
    gold=s.load(s.WORKSPACE/manifest['scoring_only']['evidence'])
    maps=clusters(annotations,s.load(s.RUN/'data/indivisible_units.json')['units'])
    if len(set(maps['linked'].values()))!=policy['dependence']['primary_linked_clusters']:raise ValueError('Dependence map drift')
    rows=[];bindings={};records={};events=defaultdict(list)
    for event in [json.loads(line) for line in (BASE/'execution_events.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]:
        if event.get('kind')=='generation_request_completed':events[event['folder']].append(event)
    for mode,out,expected in [('agentic',BASE,4160),('single_pass',BASE/'supplement/single_pass',960)]:
        status=s.load(out/'scoring/stream_status.json')
        if status['bound_answers']!=expected or status['completed_evaluations']!=expected*2 or status['active_or_queued']:
            raise ValueError('Formal generation/scoring queue is not fully reconciled')
        packet=s.load(out/'scoring/packet.json')
        if packet['count']!=expected or packet['protocol_sha256']!=s.sha(out/'protocol.json'):raise ValueError('Packet binding drift')
        bindings[str((out/'scoring/packet.json').relative_to(s.RUN))]=s.sha(out/'scoring/packet.json')
        for row in packet['items']:
            fp=s.RUN/row['generation_file']
            if s.sha(fp)!=row['generation_sha256']:raise ValueError('Generation drift')
            raw=s.load(fp);item=row['item'];qid=row['qid'];a=annotations[qid];failed=raw['status']!='answered'
            if raw.get('manifest_sha256')!=s.sha(evaluation.runner.MANIFEST):raise ValueError('Manifest drift')
            score=judged(out/'scoring',item,failed)
            rec={}
            for judge in s.JUDGES:
                root=out/'scoring'/judge/item['sample_id']
                if (root/'parsed.json').exists():
                    if judge=='gpt_sol' and s.load(root/'parsed.json').get('response_model')=='gpt-6.1-terra':
                        from test160_terra import verify_canonical
                        state=verify_canonical(root,item)
                    else:
                        state=recovery.reconcile(root,judge,item)
                    if state!='valid':raise ValueError('Saved score is not valid')
                    bindings[str((root/'parsed.json').relative_to(s.RUN))]=s.sha(root/'parsed.json')
                    rec[judge]=s.load(root/'parsed.json')['record']
            records[mode,row['model'],row['method'],qid]=rec
            usage=[];provider_costs=[];last_raw={};request_files=list((fp.parent/'requests').glob('*.request.json'))+list((fp.parent/'transport_recovery').glob('*/requests/*.request.json'))
            first=[]
            for req in request_files:
                saved=s.load(req);first.append(saved['started_utc']);bindings[str(req.relative_to(s.RUN))]=s.sha(req)
                response=req.with_name(req.name.replace('.request.json','.response.txt'))
                if response.exists():
                    bindings[str(response.relative_to(s.RUN))]=s.sha(response)
                    try:
                        body=s.load(response)
                        if not isinstance(body,dict):raise ValueError('Non-object raw response')
                        last_raw=body;u=body.get('usage') or {}
                        cost={k:body[k] for k in ('cost','billing','cost_details') if k in body}
                        if cost:provider_costs.append(dict(response=str(response.relative_to(s.RUN)),provider_fields=cost))
                    except (ValueError,TypeError):u={}
                    usage.append(u)
            ev=events[str(fp.parent)]
            seconds=(datetime.fromisoformat(max(x['utc'] for x in ev))-datetime.fromisoformat(min(first))).total_seconds() if ev and first else None
            types=('S' if a['labels']['evidence_integration']=='single' else 'M')+str(int(a['labels']['condition_discrimination']))
            scores=score['by_judge']
            strict_bounds=[avg([scores[j]['strict_bounds'][i] for j in s.JUDGES]) for i in (0,1)]
            failure_type=raw['status'] if failed else None
            if failed and mode=='single_pass' and failure_type=='response':
                choices=last_raw.get('choices',[])
                failure_type='completion_truncated' if choices and choices[0].get('finish_reason')!='stop' else 'empty_or_invalid_answer'
            observed=sum(type(u.get('prompt_tokens')) is int and type(u.get('completion_tokens')) is int for u in usage)
            r=dict(mode=mode,model=row['model'],method=row['method'],question_id=qid,type=types,knowledge_group=a['split_group'],theme=a['theme_id'],
                   fact_component=maps['fact'][qid],linked_cluster=maps['linked'][qid],conditional=item['conditional'],generation_status=raw['status'],
                   generation_failed=failed,failure_type=failure_type,evaluation_complete=failed or len(rec)==2,score=score,strict_bounds=strict_bounds,
                   evidence=evidence(qid,raw.get('delivered_lines',[]),annotations,gold),
                   characters=raw.get('knowledge_characters',0),tool_calls=len(raw.get('tool_events',[])) if mode=='agentic' else 0,
                   backend_search_calls=sum(e.get('name')=='search' for e in raw.get('tool_events',[])) if mode=='agentic' else raw.get('backend_calls',1),
                   tool_errors=sum(e.get('status')!='returned' for e in raw.get('tool_events',[])) if mode=='agentic' else 0,
                   physical_generation_requests=len(request_files),usage_observed_responses=observed,usage_missing_requests=len(request_files)-observed,
                   actual_prompt_tokens=sum(u.get('prompt_tokens',0) or 0 for u in usage),actual_completion_tokens=sum(u.get('completion_tokens',0) or 0 for u in usage),
                   usage_missing_responses=sum(type(u.get('prompt_tokens')) is not int or type(u.get('completion_tokens')) is not int for u in usage),
                   counted_input_tokens=raw.get('counted_input_tokens'),seconds=seconds,
                   transport_seconds=sum(e['seconds'] for e in ev),
                   latency_boundary='First recorded POST start through final transport event. Single-Pass initial backend ranking is outside this span; no total-wall-time comparison is claimed.',
                   provider_cost_records=provider_costs,
                   source=row['generation_file'],source_sha256=row['generation_sha256'],sample_id=item['sample_id'])
            rows.append(r)
            bindings[row['generation_file']]=row['generation_sha256']
    if len(rows)!=5120 or len({(r['mode'],r['model'],r['method'],r['question_id']) for r in rows})!=5120:raise ValueError('Formal matrix mismatch')
    return rows,maps,records,bindings


def summary(rows,maps,policy):
    first=rows[0]
    out={k:first[k] for k in ['mode','model','method']}
    out.update(n=len(rows),successes=sum(not r['generation_failed'] for r in rows),generation_failures=sum(r['generation_failed'] for r in rows),
               evaluation_complete=sum(r['evaluation_complete'] for r in rows),unknown_items=sum(r['score']['unknown_items'] for r in rows),
               missing_items=sum(r['score']['missing_items'] for r in rows),failure_types=dict(Counter(r.get('failure_type') or r['generation_status'] for r in rows if r['generation_failed'])))
    for metric in METRICS:
        point_identified=all(r['score']['composite'][metric] is not None for r in rows)
        bs=bootstrap([r['score']['bounds'][metric] for r in rows],[r['question_id'] for r in rows],maps['linked'],policy['bootstrap_resamples'],policy['seed'],point_identified)
        out[metric]=bs['mean'];out[metric+'_bounds']=bs['bounds'];out[metric+'_ci95']=bs['ci95'];out[metric+'_envelope95']=bs['identification_envelope95']
        for judge in s.JUDGES:
            vals=[number(r['score']['by_judge'][judge][metric]) for r in rows]
            out[judge+'_'+metric]=avg(vals)
    for factor in ['K','F','A']:
        eligible=[r for r in rows if factor!='A' or r['conditional']]
        values=[r['score']['composite'][factor] for r in eligible]
        out[factor]=avg(values);out[factor+'_known_n']=sum(v is not None for v in values)
        out[factor+'_applicable_n']=len(eligible)
        out[factor+'_observed_mean']=avg([v for v in values if v is not None])
        for judge in s.JUDGES:
            out[judge+'_'+factor]=avg([number(r['score']['by_judge'][judge].get(factor)) for r in eligible])
    strict=[r['strict_bounds'] for r in rows]
    out.update(strict_rate=avg([lo if lo==hi else None for lo,hi in strict]),strict_bounds=[avg([x[i] for x in strict]) for i in (0,1)],
               success_rate=out['successes']/len(rows),mean_line_recall=avg([r['evidence']['line_recall'] for r in rows]),
               complete_evidence_rate=avg([int(r['evidence']['complete']) for r in rows]),mean_span_recall=avg([r['evidence']['evidence_span_recall'] for r in rows]),
               tool_adoption_rate=sum(r['tool_calls']>0 for r in rows)/len(rows),search_adoption_rate=sum(r['backend_search_calls']>0 for r in rows)/len(rows),
               mean_tool_calls=avg([r['tool_calls'] for r in rows]),mean_search_calls=avg([r['backend_search_calls'] for r in rows]),
               mean_characters=avg([r['characters'] for r in rows]),tool_errors=sum(r['tool_errors'] for r in rows),
               actual_prompt_tokens=sum(r['actual_prompt_tokens'] for r in rows),actual_completion_tokens=sum(r['actual_completion_tokens'] for r in rows),
               physical_generation_requests=sum(r['physical_generation_requests'] for r in rows),usage_missing_responses=sum(r['usage_missing_responses'] for r in rows),
               usage_missing_requests=sum(r.get('usage_missing_requests',0) for r in rows),
               seconds_observed_mean=avg([r['seconds'] for r in rows if r['seconds'] is not None]),seconds_observed_n=sum(r['seconds'] is not None for r in rows))
    return out


def comparisons(rows,maps,policy):
    lookup={(r['mode'],r['model'],r['method'],r['question_id']):r for r in rows}
    ids=sorted(maps['linked']);result=[];per_question=[]
    for family,definition in policy['comparisons'].items():
        local=[]
        for model in MODELS:
            if family=='mode':pairs=[('single_pass',m,'agentic',m) for m in ['graph','bm25','bge_m3']]
            else:pairs=[('agentic','graph','agentic',m) for m in definition['right']]
            for lm,left,rm,right in pairs:
                ls=[lookup[lm,model,left,q] for q in ids];rs=[lookup[rm,model,right,q] for q in ids]
                for metric in METRICS:
                    bounds=[(l['score']['bounds'][metric][0]-r['score']['bounds'][metric][1],l['score']['bounds'][metric][1]-r['score']['bounds'][metric][0]) for l,r in zip(ls,rs)]
                    known=all(l['score']['composite'][metric] is not None and r['score']['composite'][metric] is not None for l,r in zip(ls,rs))
                    bs=bootstrap(bounds,ids,maps['linked'],policy['bootstrap_resamples'],policy['seed'],known)
                    test=signflip([lo for lo,hi in bounds],ids,maps['linked'],family=='mode') if known else dict(p=None,reason='Unidentified planned outcomes; no test')
                    row=dict(family=family,model=model,left_mode=lm,left_method=left,right_mode=rm,right_method=right,metric=metric,
                             difference=bs['mean'],bounds=bs['bounds'],ci95=bs['ci95'],identification_envelope95=bs['identification_envelope95'],
                             macro_bounds=bs['equal_cluster_macro_bounds'],clusters=bs['clusters'],p=test['p'],test=test,
                             sensitivity={k:bootstrap(bounds,ids,mapping,policy['bootstrap_resamples'],policy['seed'],known) for k,mapping in maps.items() if k!='linked'})
                    local.append(row)
                    for l,r,b in zip(ls,rs,bounds):
                        per_question.append(dict(family=family,model=model,left_mode=lm,left_method=left,right_mode=rm,right_method=right,metric=metric,
                            question_id=l['question_id'],type=l['type'],knowledge_group=l['knowledge_group'],linked_cluster=l['linked_cluster'],
                            difference=(l['score']['composite'][metric]-r['score']['composite'][metric]) if l['score']['composite'][metric] is not None and r['score']['composite'][metric] is not None else None,lower=b[0],upper=b[1],
                            evidence_line_recall_difference=l['evidence']['line_recall']-r['evidence']['line_recall'],
                            left_tool_calls=l['tool_calls'],right_tool_calls=r['tool_calls'],
                            judge_differences={j:number(l['score']['by_judge'][j][metric])-number(r['score']['by_judge'][j][metric]) if number(l['score']['by_judge'][j][metric]) is not None and number(r['score']['by_judge'][j][metric]) is not None else None for j in s.JUDGES}))
        if len(local)!=definition['holm_family_size']:raise ValueError('Comparison family drift')
        holm(local);result.extend(local)
    return result,per_question


def agreement(rows,records,groups,maps,policy):
    from scipy.stats import spearmanr, kendalltau
    pairs=defaultdict(list);differences=[];large=[]
    for r in rows:
        rec=records[r['mode'],r['model'],r['method'],r['question_id']]
        if set(rec)!=set(s.JUDGES):continue
        left,right=[rec[j] for j in s.JUDGES]
        lp={z['criterion_id']:z['score'] for z in left['points']};rp={z['criterion_id']:z['score'] for z in right['points']}
        pairs['K'].extend((lp[k],rp[k]) for k in lp)
        pairs['F'].append((left['fact_gate'],right['fact_gate']))
        if r['conditional']:pairs['A'].append((left['applicability_gate'],right['applicability_gate']))
        for metric in METRICS:
            l=number(r['score']['by_judge'][s.JUDGES[0]][metric]);rr=number(r['score']['by_judge'][s.JUDGES[1]][metric])
            if l is not None and rr is not None:
                d=rr-l;differences.append(dict(mode=r['mode'],model=r['model'],method=r['method'],question_id=r['question_id'],metric=metric,right_minus_left=d,absolute_difference=abs(d)))
    ranks=[];opposite=[]
    for mode in ['agentic','single_pass']:
        for model in MODELS:
            gr=[g for g in groups if g['mode']==mode and g['model']==model]
            for metric in METRICS:
                lv=[g['gpt_sol_'+metric] for g in gr];rv=[g['deepseek_flash_'+metric] for g in gr]
                known=all(type(v) in (int,float) for v in lv+rv)
                ranks.append(dict(mode=mode,model=model,metric=metric,scope='all_reported_methods',methods=len(gr),all_identified=known,
                     spearman=float(spearmanr(lv,rv).statistic) if known and len(set(lv))>1 and len(set(rv))>1 else None,
                     kendall=float(kendalltau(lv,rv).statistic) if known and len(set(lv))>1 and len(set(rv))>1 else None))
                if mode=='agentic':
                    main=[g for g in gr if g['method'] in METHODS[:9]]
                    lv9=[g['gpt_sol_'+metric] for g in main];rv9=[g['deepseek_flash_'+metric] for g in main]
                    known9=all(type(v) in (int,float) for v in lv9+rv9)
                    ranks.append(dict(mode=mode,model=model,metric=metric,scope='nine_main_methods',methods=9,all_identified=known9,
                        spearman=float(spearmanr(lv9,rv9).statistic) if known9 and len(set(lv9))>1 and len(set(rv9))>1 else None,
                        kendall=float(kendalltau(lv9,rv9).statistic) if known9 and len(set(lv9))>1 and len(set(rv9))>1 else None))
                for a,b in itertools.combinations(gr,2):
                    v=[a[j+'_'+metric] for j in s.JUDGES]+[b[j+'_'+metric] for j in s.JUDGES]
                    if all(type(z) in (int,float) for z in v):
                        ds=[a[j+'_'+metric]-b[j+'_'+metric] for j in s.JUDGES]
                        if ds[0]*ds[1]<0:opposite.append(dict(mode=mode,model=model,metric=metric,left=a['method'],right=b['method'],gpt_delta=ds[0],deepseek_delta=ds[1]))
    error=[]
    for group in groups:
        rr=[r for r in rows if all(r[k]==group[k] for k in ['mode','model','method'])]
        for metric in METRICS:
            field='eas_arith_bounds' if metric=='EAS_arith' else 'eas_geo_bounds'
            bounds=[];known=[]
            for r in rr:
                left,right=[r['score']['by_judge'][j] for j in s.JUDGES]
                bounds.append((right[field][0]-left[field][1],right[field][1]-left[field][0]))
                l=number(left[metric]);v=number(right[metric]);known.append(v-l if l is not None and v is not None else None)
            identified=all(v is not None for v in known)
            bias=bootstrap(bounds,[r['question_id'] for r in rr],maps['linked'],policy['bootstrap_resamples'],policy['seed'],identified)
            absolute=[(0 if lo<=0<=hi else min(abs(lo),abs(hi)),max(abs(lo),abs(hi))) for lo,hi in bounds]
            mae=bootstrap(absolute,[r['question_id'] for r in rr],maps['linked'],policy['bootstrap_resamples'],policy['seed'],identified)
            error.append(dict(mode=group['mode'],model=group['model'],method=group['method'],metric=metric,n=len(rr),known_pairs=sum(v is not None for v in known),
                mae=mae['mean'],mae_bounds=mae['bounds'],mae_ci95=mae['ci95'],mae_envelope95=mae['identification_envelope95'],
                bias_deepseek_minus_gpt=bias['mean'],bias_bounds=bias['bounds'],bias_ci95=bias['ci95'],bias_envelope95=bias['identification_envelope95']))
    return dict(ordinal={k:ordinal_agreement(v) for k,v in pairs.items()},rank_correlations=ranks,opposite_method_directions=opposite,
                method_errors=error,largest_differences=sorted(differences,key=lambda r:(-r['absolute_difference'],r['question_id']))[:100],
                limitation='Judge agreement and rank agreement are not evidence of absolute correctness; original independent human audit failed thresholds.')


def figures(groups,paired,rows):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':9,'axes.spines.top':False,'axes.spines.right':False,'svg.fonttype':'none','pdf.fonttype':42})
    dest=OUT/'figures';dest.mkdir(exist_ok=True)
    files=[]
    def save(fig,name,tight=True):
        if tight:fig.tight_layout()
        for ext in ['svg','pdf','png']:
            path=dest/(name+'.'+ext);fig.savefig(path,dpi=300,bbox_inches='tight');files.append(path)
        plt.close(fig)
    by={(g['mode'],g['model'],g['method']):g for g in groups}
    fig,axes=plt.subplots(1,2,figsize=(11,5.1),sharex=True)
    for ax,model in zip(axes,MODELS):
        for i,m in enumerate(METHODS):
            g=by['agentic',model,m];v=g['EAS_arith'];ci=g['EAS_arith_ci95']
            if v is not None:
                ax.barh(i,v,color='#176b8a' if i<9 else '#bc784b',alpha=.88)
                if ci:ax.errorbar(v,i,xerr=np.array([[max(0,v-ci[0])],[max(0,ci[1]-v)]]),fmt='none',ecolor='#20334b',capsize=2)
            else:
                lo,hi=g['EAS_arith_bounds'];ax.barh(i,hi-lo,left=lo,color='#d1d9df',hatch='//')
        ax.set(yticks=range(13),yticklabels=[SHORT[m] for m in METHODS],xlim=(0,102),title=model,xlabel='Dual-judge EAS arithmetic / 100');ax.invert_yaxis()
    save(fig,'test160_agentic_comparison')
    fig,axes=plt.subplots(1,2,figsize=(10,3.8),sharey=True)
    for ax,model in zip(axes,MODELS):
        for offset,mode,color in [(-.18,'agentic','#176b8a'),(.18,'single_pass','#bc784b')]:
            for i,m in enumerate(['graph','bm25','bge_m3']):
                g=by[mode,model,m];v=g['EAS_arith']
                if v is not None:ax.bar(i+offset,v,width=.34,color=color,label=mode if i==0 else None)
                else:
                    lo,hi=g['EAS_arith_bounds'];ax.bar(i+offset,hi-lo,bottom=lo,width=.34,color='#d1d9df',hatch='//')
        ax.set(xticks=range(3),xticklabels=['Source graph','BM25','BGE-M3'],ylim=(0,102),title=model,ylabel='Dual-judge EAS arithmetic / 100');ax.legend(frameon=False)
    save(fig,'test160_mode_comparison')
    fig,axes=plt.subplots(1,2,figsize=(10,3.4),sharex=True)
    for ax,model in zip(axes,MODELS):
        rs=[r for r in paired if r['family']=='ablation' and r['model']==model and r['metric']=='EAS_arith']
        ax.axvline(0,color='#aab5bf',lw=1)
        for i,r in enumerate(rs):
            ci=r['ci95'] or r['identification_envelope95'];v=r['difference']
            ax.plot(ci,[i,i],color='#176b8a',lw=2)
            if v is not None:ax.plot(v,i,'o',color='#176b8a')
        ax.set(yticks=range(4),yticklabels=[SHORT[r['right_method']] for r in rs],title=model,xlabel='Full graph minus ablation (points)');ax.invert_yaxis()
    save(fig,'test160_ablation_differences')
    fig,axes=plt.subplots(1,2,figsize=(10,5),sharey=True)
    for ax,model in zip(axes,MODELS):
        data=np.full((13,4),np.nan)
        for i,m in enumerate(METHODS):
            for j,t in enumerate(['S0','S1','M0','M1']):
                rr=[r for r in rows if (r['mode'],r['model'],r['method'],r['type'])==('agentic',model,m,t)]
                v=avg([r['score']['composite']['EAS_arith'] for r in rr]);data[i,j]=np.nan if v is None else v
        im=ax.imshow(data,vmin=0,vmax=100,cmap='YlGnBu',aspect='auto')
        ax.set(xticks=range(4),xticklabels=['S0','S1','M0','M1'],yticks=range(13),yticklabels=[SHORT[m] for m in METHODS],title=model)
    fig.subplots_adjust(left=.2,right=.86,wspace=.12,bottom=.12,top=.92)
    color_axis=fig.add_axes([.9,.22,.018,.58])
    fig.colorbar(im,cax=color_axis,label='EAS arithmetic')
    save(fig,'test160_question_types',tight=False)
    fig,axes=plt.subplots(1,2,figsize=(10,4))
    axes[0].plot([0,100],[0,100],color='#aab5bf',lw=1)
    for model,marker in zip(MODELS,['o','s']):
        gr=[g for g in groups if g['mode']=='agentic' and g['model']==model]
        known=[g for g in gr if g['gpt_sol_EAS_arith'] is not None and g['deepseek_flash_EAS_arith'] is not None]
        axes[0].scatter([g['gpt_sol_EAS_arith'] for g in known],[g['deepseek_flash_EAS_arith'] for g in known],marker=marker,label=model)
        known=[g for g in gr if g['EAS_arith'] is not None]
        axes[1].scatter([(g['actual_prompt_tokens']+g['actual_completion_tokens'])/160 for g in known],[g['EAS_arith'] for g in known],marker=marker,label=model)
    axes[0].set(xlabel='GPT-6 Sol EAS arithmetic',ylabel='DeepSeek Flash EAS arithmetic',xlim=(0,100),ylim=(0,100));axes[0].legend(frameon=False)
    axes[1].set(xlabel='Observed generation tokens / planned question',ylabel='Dual-judge EAS arithmetic');axes[1].legend(frameon=False)
    save(fig,'test160_judges_and_resources')
    fig,axes=plt.subplots(1,2,figsize=(11,4),sharey=True)
    for ax,model in zip(axes,MODELS):
        gr=[by['agentic',model,m] for m in METHODS]
        ax.plot(range(13),[g['tool_adoption_rate'] for g in gr],'o-',label='LLM tool adoption',color='#176b8a')
        ax.plot(range(13),[g['mean_line_recall'] for g in gr],'s-',label='Required-line recall',color='#bc784b')
        ax.set(xticks=range(13),xticklabels=[SHORT[m] for m in METHODS],ylim=(-.03,1.03),title=model,ylabel='Rate');ax.tick_params(axis='x',labelrotation=60);ax.legend(frameon=False)
    save(fig,'test160_tools_and_evidence')
    return files


def run(authorization):
    if s.sha(Path(__file__))!=s.sha(BASE/'runtime/test160_report.py'):
        raise ValueError('Operational report implementation changed after its execution snapshot')
    if s.sha(s.RUN/'release/protocol/test160_analysis.json')!=s.sha(BASE/'runtime/test160_analysis.json'):
        raise ValueError('Operational analysis schedule changed after its execution snapshot')
    policy=s.load(s.RUN/'release/protocol/test160_analysis.json')
    rows,maps,records,bindings=load_rows(authorization,policy)
    groups=[]
    for mode in ['agentic','single_pass']:
        for model in MODELS:
            for method in (METHODS if mode=='agentic' else ['graph','bm25','bge_m3']):
                gr=[r for r in rows if (r['mode'],r['model'],r['method'])==(mode,model,method)]
                if len(gr)!=160:raise ValueError('Fixed denominator not 160')
                groups.append(summary(gr,maps,policy))
    paired,paired_questions=comparisons(rows,maps,policy)
    robust=agreement(rows,records,groups,maps,policy)
    subgroups=[]
    for variable in ['type','knowledge_group','theme']:
        for group in groups:
            rr=[r for r in rows if all(r[k]==group[k] for k in ['mode','model','method'])]
            for value in sorted({r[variable] for r in rr}):
                subset=[r for r in rr if r[variable]==value]
                subgroups.append(dict(variable=variable,value=value,**summary(subset,maps,policy)))
    judge_resources=[]
    for mode,prefix in [('agentic',BASE),('single_pass',BASE/'supplement/single_pass')]:
        for judge in s.JUDGES:
            ledger=prefix/'scoring'/judge/'recovery_events.jsonl'
            events=[json.loads(z) for z in ledger.read_text(encoding='utf-8').splitlines() if z.strip()] if ledger.exists() else []
            provider_costs=[]
            for folder in (prefix/'scoring'/judge).glob('T*/recovery/attempt_*'):
                for file in folder.glob('*'):
                    if file.is_file():bindings[str(file.relative_to(s.RUN))]=s.sha(file)
                raw=folder/'response.txt'
                if raw.exists():
                    try:body=s.load(raw)
                    except (ValueError,TypeError):continue
                    if not isinstance(body,dict):continue
                    cost={k:body[k] for k in ('cost','billing','cost_details') if k in body}
                    if cost:provider_costs.append(dict(response=str(raw.relative_to(s.RUN)),provider_fields=cost))
            judge_resources.append(dict(mode=mode,judge=judge,physical_requests=len(events),states=dict(Counter(e['status'] for e in events)),
                observed_input_tokens=sum(e.get('usage',{}).get('input_tokens',0) for e in events),
                observed_output_tokens=sum(e.get('usage',{}).get('output_tokens',0) for e in events),
                observed_reasoning_tokens=sum(e.get('usage',{}).get('reasoning_tokens') or 0 for e in events),
                usage_missing=sum(not e.get('usage') for e in events),actual_cost=provider_costs or 'Unknown'))
    table=OUT/'tables'
    csv_file(table/'comparison.csv',[g for g in groups if g['mode']=='agentic'])
    csv_file(table/'single_pass.csv',[g for g in groups if g['mode']=='single_pass'])
    flat=[]
    for r in rows:
        score=r['score'];v={k:x for k,x in r.items() if k not in ['score','evidence']}
        v.update(score['composite']);v.update({k+'_bounds':score['bounds'][k] for k in METRICS})
        for j in s.JUDGES:v.update({j+'_'+k:score['by_judge'][j].get(k) for k in ['K','F','A','EAS_arith','EAS_geo','Strict']})
        v.update(r['evidence']);v.update(unknown_items=score['unknown_items'],missing_items=score['missing_items']);flat.append(v)
    csv_file(table/'per_answer.csv',flat)
    csv_file(table/'paired_comparisons.csv',paired)
    csv_file(table/'paired_differences.csv',paired_questions)
    paired_subgroups=[]
    pair_keys=['family','model','left_mode','left_method','right_mode','right_method','metric']
    for variable in ['type','knowledge_group']:
        grouped=defaultdict(list)
        for r in paired_questions:grouped[tuple(r[k] for k in pair_keys)+(r[variable],)].append(r)
        for key,rr in grouped.items():
            known=[r['difference'] for r in rr if r['difference'] is not None]
            paired_subgroups.append(dict(**dict(zip(pair_keys,key[:-1])),variable=variable,value=key[-1],n=len(rr),known_pairs=len(known),
                difference=avg([r['difference'] for r in rr]),bounds=[avg([r[k] for r in rr]) for k in ['lower','upper']],
                wins=sum(v>0 for v in known),ties=sum(v==0 for v in known),losses=sum(v<0 for v in known),
                mean_evidence_line_recall_difference=avg([r['evidence_line_recall_difference'] for r in rr]),
                interpretation='Descriptive paired subgroup; no confirmatory subgroup test'))
    csv_file(table/'paired_subgroups.csv',paired_subgroups)
    csv_file(table/'subgroups.csv',subgroups)
    csv_file(table/'judge_method_differences.csv',robust['method_errors'])
    csv_file(table/'judge_opposite_directions.csv',robust['opposite_method_directions'])
    csv_file(table/'judge_large_differences.csv',robust['largest_differences'])
    csv_file(table/'generation_failures.csv',[r for r in flat if r['generation_failed']])
    csv_file(table/'unresolved_or_unknown.csv',[r for r in flat if r['unknown_items'] or r['missing_items'] and not r['generation_failed']])
    csv_file(table/'judge_resources.csv',judge_resources)
    s.save(OUT/'test160_results.json',dict(updated_utc=s.now(),manifest_sha256=s.sha(evaluation.runner.MANIFEST),
           analysis_specification_sha256=s.sha(s.RUN/'release/protocol/test160_analysis.json'),groups=groups,paired=paired,
           source_representation=s.load(BASE/'scoring/source_policy.json'),
           judge_robustness=robust,judge_resources=judge_resources,per_answer=rows,
           dependence_counts={k:len(set(v.values())) for k,v in maps.items()},
           confidence_interval_scope='Nominal percentile 95% intervals, not simultaneous intervals; Holm adjustments apply separately to the complete declared test families.',
           latency_scope='Observed transport spans exclude Single-Pass initial ranking and do not establish complete workflow wall-time differences. Tokens, calls, characters and available spans are reported without imputing missing resource measurements.',
           limitations=['Original independent human audit failed original thresholds','Analysis schedule specified after generation start and before score inspection','Historically exposed source questions; no historically unseen-document claim','Unknown/missing retain fixed-denominator bounds','Mode differences describe whole workflows; graph relation causality not isolated']))
    files=figures(groups,paired,rows)
    # Machine-readable LaTeX cells are provided without modifying manuscript prose.
    lines=['% Test160; per-answer dual mean; fixed 160-question denominator.','% Unknown estimates are --; bounds and uncertainty are in paired_comparisons.csv.']
    for g in groups:
        def fmt(v):return '--' if v is None else '%.2f'%v
        label=SHORT[g['method']].replace('&',r'\&')
        lines.append(' & '.join([g['mode'].replace('_',r'\_'),g['model'],label,fmt(g['EAS_arith']),fmt(g['EAS_geo']),fmt(g['K']),fmt(g['F']),fmt(g['A'])])+r' \\')
    (table/'test160_cells.tex').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    manuscript=s.WORKSPACE/'graduation-thesis-materials/graduation-manuscript/assets/chapter2_test160'
    manuscript.mkdir(parents=True,exist_ok=True)
    publication={}
    for file in files+[table/'test160_cells.tex']:
        target=manuscript/file.name
        shutil.copyfile(file,target)
        if s.sha(file)!=s.sha(target):raise ValueError('Publication artifact copy mismatch')
        publication[str(target.relative_to(s.WORKSPACE))]=s.sha(target)
    s.save(OUT/'test160_publication_assets.json',dict(files=publication,manuscript_prose_modified=False))
    failed=sum(r['generation_failed'] for r in rows);unresolved=sum(not r['evaluation_complete'] for r in rows)
    unknown=sum(r['score']['unknown_items'] for r in rows)
    report=['Test160 正式实验总结',f'生成终态：5120/5120（Agentic 4160，Single-Pass 960）；生成失败 {failed} 条。',
            f'双裁判处理已覆盖全部正式回答；未取得完整双裁判有效记录 {unresolved} 条；显式 Unknown 项 {unknown}。生成失败依冻结规则计零，Unknown和缺失保留上下界。',
            '主要结果（逐回答先算EAS，再取双裁判平均；每配置固定160题）：']
    for model in MODELS:
        main=[g for g in groups if g['mode']=='agentic' and g['model']==model and g['method'] in METHODS[:9]]
        identified=[g for g in main if g['EAS_arith'] is not None]
        if len(identified)==9:
            best=max(identified,key=lambda g:g['EAS_arith']);graph=next(g for g in main if g['method']=='graph')
            report.append(f'{model}：九主方法最高均值为 {SHORT[best["method"]]}（{best["EAS_arith"]:.2f}）；完整来源图 {graph["EAS_arith"]:.2f}。这是描述排序，显著性另按预定比较族报告。')
        else:report.append(f'{model}：存在未识别的完整分母均值，不按完整案例均值宣布方法排名。')
    report.append('Single-Pass减Agentic的同题算术差：')
    for r in paired:
        if r['family']=='mode' and r['metric']=='EAS_arith':
            report.append(f'{r["model"]} / {SHORT[r["left_method"]]}：{r["difference"] if r["difference"] is not None else "Unknown"}；95%区间/识别包络 {r["ci95"] or r["identification_envelope95"]}。')
    report.append('没有达到预期或方向不稳的结果：')
    for r in paired:
        if r['metric']=='EAS_arith' and r['family'] in ('main','ablation') and (r['difference'] is None or r['difference']<=0 or not r['reject']):
            report.append(f'{r["model"]} 完整图对 {SHORT[r["right_method"]]}：差值 {r["difference"]}，Holm p={r["holm_adjusted_p"]}；未确认预期正向优势。')
    report.extend(['结论边界：原独立人工审计未达门槛；裁判一致性不能证明绝对正确。20个关联簇的独立性和符号交换假设是统计条件，不是数据事实。统计细则制定于生成启动后、分数查看前，不能称为生成前预注册。模式差异不能全部归因于图谱关系。',
                   '有限待办：核查unresolved_or_unknown.csv与judge_large_differences.csv，保留全部原分、失败与Unknown；不根据分数补跑或更换裁判。',
                   '可用于论文：tables/comparison.csv、single_pass.csv、paired_comparisons.csv、subgroups.csv、test160_cells.tex，以及figures/下六组SVG/PDF/300dpi PNG。'])
    (OUT/'test160_summary.txt').write_text('\n\n'.join(report)+'\n',encoding='utf-8')
    def fmt(v):return 'Unknown' if v is None else f'{v:.2f}'
    body='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>Test160 正式结果</title><style>body{font:15px system-ui;max-width:1280px;margin:32px auto;padding:0 20px;color:#20334b}table{border-collapse:collapse;width:100%}td,th{padding:9px;border-bottom:1px solid #dfe6ed;text-align:right}td:first-child,th:first-child{text-align:left}a{color:#12698c}img{width:100%;max-width:1100px}.note{padding:16px;background:#edf4f8}</style><h1>第2章 Test160 正式结果</h1>'
    body+=f'<p>5120 条生成终态；失败 {failed} 条；未完整双评 {unresolved} 条；显式 Unknown 项 {unknown}。</p><p class="note">每配置固定160题。主指标为逐回答双裁判平均 EAS_arith；EAS_geo 同时报告。原人工审计未达最初门槛；统计细则在生成开始后、查看分数前固定。相关性以20个关联簇处理，工作模式差异不等于单一图关系的因果效果。</p>'
    body+='<p><a href="test160_summary.txt">简洁总结</a> · <a href="test160_results.json">完整结果与边界</a> · <a href="tables/per_answer.csv">5120逐题</a> · <a href="tables/paired_comparisons.csv">配对统计与校正</a> · <a href="tables/paired_differences.csv">逐题配对差异</a> · <a href="tables/subgroups.csv">四类题型/知识组/主题</a> · <a href="tables/judge_large_differences.csv">裁判分歧</a> · <a href="tables/judge_resources.csv">评分资源</a> · <a href="dev40.html">Dev40历史开发</a></p>'
    for mode,title in [('agentic','Agentic 13方法 × 2模型'),('single_pass','Single-Pass 3后端 × 2模型')]:
        body+='<h2>'+title+'</h2><table><tr><th>模型 / 方法</th><th>EAS算术</th><th>95% CI或包络</th><th>EAS几何</th><th>K / F / A</th><th>成功/160</th><th>用工具</th><th>必要行召回</th></tr>'
        for g in groups:
            if g['mode']!=mode:continue
            ci=g['EAS_arith_ci95'] or g['EAS_arith_envelope95']
            body+=f'<tr><td>{g["model"]} / {SHORT[g["method"]]}</td><td>{fmt(g["EAS_arith"])}</td><td>{ci[0]:.2f}–{ci[1]:.2f}</td><td>{fmt(g["EAS_geo"])}</td><td>{fmt(g["K"])} / {fmt(g["F"])} / {fmt(g["A"])}</td><td>{g["successes"]}/160</td><td>{g["tool_adoption_rate"]:.1%}</td><td>{g["mean_line_recall"]:.1%}</td></tr>'
        body+='</table>'
    for path in files:
        if path.suffix=='.svg':body+='<h2>'+html.escape(path.stem)+'</h2><a href="figures/'+path.with_suffix('.pdf').name+'">PDF</a><img src="figures/'+path.name+'" alt="'+path.stem+'">'
    body+='<h2>总结与有限问题</h2><pre style="white-space:pre-wrap">'+html.escape('\n\n'.join(report))+'</pre></html>'
    (OUT/'index.html').write_text(body,encoding='utf-8')
    bindings.update({str(p.relative_to(s.RUN)):s.sha(p) for p in [s.RUN/'release/protocol/test160_analysis.json',s.RUN/'release/protocol/test160_approval.json',BASE/'scoring/source_policy.json']})
    s.save(OUT/'test160_provenance.json',dict(manifest_sha256=s.sha(evaluation.runner.MANIFEST),source_hashes=bindings,
           runtime_source_hashes={p.name:s.sha(p) for p in (BASE/'runtime').glob('*.py')},report_source_sha256=s.sha(Path(__file__)),
           derived_files={str(p.relative_to(s.RUN)):s.sha(p) for p in list(table.glob('*.csv'))+files+[OUT/'test160_results.json',OUT/'test160_summary.txt',OUT/'index.html']},
           raw_requests_and_responses_preserved=True,actual_cost='Unknown unless explicitly returned by provider'))
    readme=s.RUN/'README.md';text=readme.read_text(encoding='utf-8')
    text=text.replace('生成与双裁判评分持续运行。','全部生成已达到终态，双裁判处理完成；失败和未决/Unknown详见正式结果与总结。')
    text=text.replace('正式测试执行中，`results/tables/comparison.csv` 与 `per_answer.csv` 仍是既有 Dev40 派生表，不能引用为 Test160 结果；开发表另保留字节相同的',
                      '正式测试处理已完成，`results/tables/comparison.csv` 与 `per_answer.csv` 为本轮 Test160 结果；Dev40 开发表保留于')
    text=text.replace('全部正式处理完成后由控制器发布 Test160 表、图和总结。','本次控制器已发布 Test160 表、图和总结。')
    readme.write_text(text,encoding='utf-8')
    print(json.dumps(dict(formal_answers=5120,generation_failures=failed,unresolved_evaluations=unresolved,unknown_items=unknown,figures=len(files))))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--authorization',type=Path,required=True)
    run(p.parse_args().authorization)
