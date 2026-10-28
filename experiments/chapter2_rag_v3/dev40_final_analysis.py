"""Full-denominator Single-Pass, Agentic and finalist paired diagnostics."""
import runtime_layout as layout
import csv
import html
import json
from pathlib import Path
import statistics
import single_pass_dev40 as s
from judge_contract import calculate,joint_metrics

OUT=layout.asset('results')
KEYS=('K','F','A','EAS_arith','EAS_geo')


def number(x):
    if type(x) in (int,float):return x
    try:return float(x)
    except (TypeError,ValueError):return None


def mean(xs):
    return statistics.mean(xs) if xs and all(type(x) in (int,float) for x in xs) else None


def judged(folder,item,failed=False):
    metrics={};records={}
    for judge in s.JUDGES:
        p=folder/judge/item['sample_id']/'parsed.json'
        if p.exists():
            record=s.load(p)['record'];records[judge]=record
            metrics[judge]=joint_metrics(record,[c['criterion_id'] for c in item['criteria']],item['conditional'],failed)
        else:
            metrics[judge]=calculate([None]*len(item['criteria']),None,
                    None if item['conditional'] else 'not_applicable',item['conditional'],failed)
    composite={k:mean([number(metrics[j].get(k)) for j in s.JUDGES]) for k in KEYS}
    bounds={k:[mean([metrics[j][field][i] for j in s.JUDGES]) for i in (0,1)]
            for k,field in [('EAS_arith','eas_arith_bounds'),('EAS_geo','eas_geo_bounds')]}
    return dict(composite=composite,bounds=bounds,by_judge=metrics,complete=len(records)==2,
                unknown_items=sum(m['unknown_items'] for m in metrics.values()),
                missing_items=sum(m['missing_items'] for m in metrics.values()))


def evidence(qid,delivered,annotations,gold):
    got={(r['path'],r['line']) for r in delivered};needed=set();spans=[]
    for eid in annotations[qid]['required_evidence_ids']:
        e=gold[eid];span={(e['path'],n) for n in range(e['line_start'],e['line_end']+1)}
        needed|=span;spans.append(span)
    return dict(line_recall=len(got&needed)/len(needed),complete=needed<=got,
                evidence_span_recall=sum(z<=got for z in spans)/len(spans))


def summarize(rows):
    n=len(rows)
    return dict(n=n,dual_scored=sum(r['score']['complete'] for r in rows),
        generation_failures=sum(r['generation_failed'] for r in rows),
        unknown_items=sum(r['score']['unknown_items'] for r in rows),
        missing_items=sum(r['score']['missing_items'] for r in rows),
        means={k:mean([r['score']['composite'][k] for r in rows if k!='A' or r.get('conditional',True)]) for k in KEYS},
        factor_known_n={k:sum(r['score']['composite'][k] is not None for r in rows) for k in ('K','F','A')},
        factor_observed_means={k:mean([r['score']['composite'][k] for r in rows if r['score']['composite'][k] is not None]) for k in ('K','F','A')},
        bounds={k:[sum(r['score']['bounds'][k][i] for r in rows)/n for i in (0,1)] for k in ('EAS_arith','EAS_geo')},
        mean_line_recall=statistics.mean(r['evidence']['line_recall'] for r in rows),
        complete_required_evidence=sum(r['evidence']['complete'] for r in rows),
        mean_characters=statistics.mean(r['characters'] for r in rows),
        with_tool_calls=sum(r['tool_calls']>0 for r in rows),
        mean_tool_calls=statistics.mean(r['tool_calls'] for r in rows),
        mean_backend_search_calls=statistics.mean(r.get('backend_search_calls',0) for r in rows),
        with_backend_search=sum(r.get('backend_search_calls',0)>0 for r in rows),
        prompt_tokens_observed=sum(r['prompt_tokens'] or 0 for r in rows),
        completion_tokens_observed=sum(r['completion_tokens'] or 0 for r in rows),
        usage_missing=sum(r['prompt_tokens'] is None or r['completion_tokens'] is None for r in rows),
        judge_means={j:{k:mean([r['score'].get('by_judge',{}).get(j,{}).get(k) for r in rows if k!='A' or r.get('conditional',True)]) for k in KEYS} for j in s.JUDGES})


def deltas(rows,key):
    known=[r[key] for r in rows if r.get(key) is not None]
    return dict(n=len(rows),paired_known=len(known),mean=mean(known),
        wins=sum(x>0 for x in known),ties=sum(x==0 for x in known),losses=sum(x<0 for x in known),
        standard_error=statistics.stdev(known)/len(known)**.5 if len(known)>1 else None,
        interpretation='Exploratory within-Dev paired description, no confirmatory significance claim')


def run():
    from dev40_supplement import original,ROOT as SUPPLEMENT
    from dev40_retrieval_study import STUDY
    OUT.mkdir(exist_ok=True)
    annotations={x['id']:x for x in s.load(s.SPLIT/'gold/dev40/annotations.json')}
    gold=s.load(s.SPLIT/'gold/dev40/evidence.json')
    qs=s.load(s.QUESTIONS)
    original_packet=s.load(s.OUT/'scoring/packet.json')
    items={(r['model'],r['method'],r['qid']):r['item'] for r in original_packet['items']}
    ap=s.load(s.RUN/'experiments/agentic/dev40/scoring/packet.json')
    meta={(r['model'],r['method'],r['question_id']):r for r in ap['private']}
    scores=list(csv.DictReader((s.RUN/'experiments/agentic/dev40/results/scores.csv').open(encoding='utf-8-sig')))
    scored={}
    for row in scores:
        if row['judge'] in s.JUDGES:scored.setdefault((row['model'],row['method'],row['question_id']),[]).append(row)
    sp=[];agent=[];pairs=[]
    for model in s.MODELS:
        for method in s.METHODS:
            for q in qs:
                qid=q['id'];key=(model,method,qid);item=items[key]
                cfg=method+'__'+model
                choices=[s.OUT/'generation'/cfg/qid]+sorted((s.OUT/'generation_recovery'/cfg/qid).glob('attempt_*'))
                folder=next(p for p in choices if (p/'result.json').exists() and s.load(p/'result.json').get('status')=='success')
                raw=s.load(folder/'result.json');ret=s.load(folder/'retrieval.json')
                r=dict(model=model,method=method,question_id=qid,conditional=item['conditional'],generation_failed=raw.get('generation_failed',False),
                    score=judged(s.OUT/'scoring',item),evidence=evidence(qid,ret['delivered_lines'],annotations,gold),
                    tool_calls=0,backend_search_calls=1,characters=ret['delivered_characters'],prompt_tokens=raw.get('usage',{}).get('prompt_tokens'),
                    completion_tokens=raw.get('usage',{}).get('completion_tokens'),source=str(folder/'result.json'),
                    source_sha256=s.sha(folder/'result.json'))
                sp.append(r)
                m=meta[key];ar=s.load(s.RUN/m['source_file']);old=scored[key]
                assert {x['judge'] for x in old}==set(s.JUDGES) and len(old)==2
                ac={k:mean([number(x[k]) for x in old]) for k in KEYS}
                ab={k:[mean([json.loads(x[field])[i] for x in old]) for i in (0,1)]
                    for k,field in [('EAS_arith','eas_arith_bounds'),('EAS_geo','eas_geo_bounds')]}
                actual_usage=[t.get('response',{}).get('raw_response',t.get('response',{}).get('response',{})).get('usage',{}) for t in ar['turns']]
                a=dict(model=model,method=method,question_id=qid,conditional=item['conditional'],generation_failed=m['status']!='answered',
                    score=dict(composite=ac,bounds=ab,by_judge={x['judge']:{k:number(x[k]) for k in KEYS} for x in old},complete=all(x['judge_record_present']=='True' for x in old) or m['status']!='answered',
                               unknown_items=sum(int(x['unknown_items']) for x in old),missing_items=sum(int(x['missing_items']) for x in old)),
                    evidence=evidence(qid,ar.get('delivered_lines',[]),annotations,gold),tool_calls=len(ar.get('tool_events',[])),
                    backend_search_calls=sum(e.get('name')=='search' for e in ar.get('tool_events',[])),
                    characters=ar.get('knowledge_characters',0),prompt_tokens=sum(x.get('prompt_tokens',0) for x in actual_usage) if all('prompt_tokens' in x for x in actual_usage) else None,
                    completion_tokens=ar.get('actual_completion_tokens'),source=m['source_file'],source_sha256=m['source_sha256'])
                agent.append(a)
                pair=dict(model=model,method=method,question_id=qid,
                    delta={k:r['score']['composite'][k]-ac[k] if r['score']['composite'][k] is not None and ac[k] is not None else None for k in KEYS})
                pairs.append(pair)
    summary=[]
    for model in s.MODELS:
        for method in s.METHODS:
            group=[r for r in sp if r['model']==model and r['method']==method]
            ag=[r for r in agent if r['model']==model and r['method']==method]
            pr=[dict(r,**r['delta']) for r in pairs if r['model']==model and r['method']==method]
            summary.append(dict(model=model,method=method,single_pass=summarize(group),agentic=summarize(ag),
                                paired={k:deltas(pr,k) for k in ('EAS_arith','EAS_geo')}))
    s.save(OUT/'single_pass_results.json',dict(updated_utc=s.now(),denominator=240,groups=summary,
        per_answer=sp,agentic_per_answer=agent,paired=pairs,
        rules='EAS estimates require all 40 answers; unknown/missing retain 40-answer bounds, no complete-case aggregate substitution. K/F on failures remain undefined. A has 20 applicable questions per 40.',
        primary='Per-answer arithmetic mean of two judges EAS_arith',test160_started=False))
    supplement=[]
    for mode in ('single_pass','agentic'):
        out=SUPPLEMENT/('single_pass_corrected' if mode=='single_pass' and (SUPPLEMENT/'single_pass_corrected/scoring/packet.json').exists() else mode)
        if not (out/'scoring/packet.json').exists():continue
        packet=s.load(out/'scoring/packet.json');group=[]
        for row in packet['items']:
            model,qid=row['model'],row['qid'];p=out/'generation'/('top5__'+model)/qid;raw=s.load(p/'result.json')
            failed=raw.get('generation_failed',False)
            if mode=='single_pass':
                ret=s.load(p/'retrieval.json');lines=ret['delivered_lines'];chars=ret['delivered_characters'];calls=0
                usage=raw.get('usage',{});prompt=usage.get('prompt_tokens');completion=usage.get('completion_tokens')
                baseline=next(r for r in sp if (r['model'],r['method'],r['question_id'])==(model,'graph',qid))
            else:
                lines=raw.get('delivered_lines',[]);chars=raw.get('knowledge_characters',0);calls=len(raw.get('tool_events',[]))
                prompt=raw.get('counted_input_tokens');completion=raw.get('actual_completion_tokens')
                baseline=next(r for r in agent if (r['model'],r['method'],r['question_id'])==(model,'graph',qid))
            score=judged(out/'scoring',row['item'],failed)
            r=dict(model=model,method='graph_top5',question_id=qid,conditional=row['item']['conditional'],generation_failed=failed,score=score,
                evidence=evidence(qid,lines,annotations,gold),characters=chars,tool_calls=calls,
                backend_search_calls=1 if mode=='single_pass' else sum(e.get('name')=='search' for e in raw.get('tool_events',[])),
                prompt_tokens=prompt,completion_tokens=completion,reused=(p/'reuse.json').exists(),
                baseline=baseline['score']['composite'],baseline_judges=baseline['score'].get('by_judge',{}))
            r.update({k:score['composite'][k]-r['baseline'][k] if score['composite'][k] is not None and r['baseline'][k] is not None else None for k in ('EAS_arith','EAS_geo')})
            group.append(r)
        for model in s.MODELS:
            gr=[r for r in group if r['model']==model]
            supplement.append(dict(mode=mode,model=model,summary=summarize(gr),
                reused_answers=sum(r['reused'] for r in gr),judge_delta={j:{k:mean([(r['score']['by_judge'][j][k]-r['baseline_judges'][j][k]) if type(r['score']['by_judge'][j].get(k)) in (int,float) and type(r['baseline_judges'][j].get(k)) in (int,float) else None for r in gr]) for k in ('EAS_arith','EAS_geo')} for j in s.JUDGES},paired={k:deltas(gr,k) for k in ('EAS_arith','EAS_geo')},per_answer=gr))
    s.save(OUT/'supplement_results.json',dict(groups=supplement,test160_started=False,
        transport_control='Use single_pass_corrected when present; 12 prior 8B Top-5 calls omitted baseline /no_think, retained but excluded from primary candidate selection'))
    body='<!doctype html><meta charset="utf-8"><title>Dev40最终结果</title><style>body{font:16px system-ui;max-width:1250px;margin:40px auto;color:#213547}table{border-collapse:collapse;width:100%}th,td{padding:10px;border-bottom:1px solid #ddd;text-align:right}td:first-child,th:first-child{text-align:left}a{color:#176b8a}</style><h1>Dev40最终结果</h1><p><a href="../README.md">总入口</a> · <a href="single_pass_results.json">逐题、成本和配对</a> · <a href="supplement_results.json">Top-5及Agentic迁移</a> · <a href="../03_dev_experiments/dev40/retrieval_study/offline_evaluation.json">固定查询机制</a></p><p>原独立人工审计未达原门槛；双裁判为固定测量工具。主指标为逐答双裁判平均EAS_arith；EAS_geo及证据为辅助。每格保留40题。</p><table><tr><th>模型 / 后端</th><th>双评</th><th>SP EAS算术</th><th>SP EAS几何</th><th>Agentic算术</th><th>配对差</th><th>SP证据召回</th><th>Agentic用工具</th></tr>'
    def fmt(v):return '待完整' if v is None else f'{v:.2f}'
    for r in summary:
        spg,ag=r['single_pass'],r['agentic']
        body+=f'<tr><td>{r["model"]} / {r["method"]}</td><td>{spg["dual_scored"]}/40</td><td>{fmt(spg["means"]["EAS_arith"])}</td><td>{fmt(spg["means"]["EAS_geo"])}</td><td>{fmt(ag["means"]["EAS_arith"])}</td><td>{fmt(r["paired"]["EAS_arith"]["mean"])}</td><td>{spg["mean_line_recall"]:.1%}</td><td>{ag["with_tool_calls"]}/40</td></tr>'
    body+='</table><h2>有限Top-5验证</h2><table><tr><th>模式/模型</th><th>双评</th><th>算术</th><th>几何</th><th>算术配对差</th><th>胜/平/负</th></tr>'
    for r in supplement:
        g=r['summary'];d=r['paired']['EAS_arith']
        body+=f'<tr><td>{r["mode"]} / {r["model"]}</td><td>{g["dual_scored"]}/{g["n"]}</td><td>{fmt(g["means"]["EAS_arith"])}</td><td>{fmt(g["means"]["EAS_geo"])}</td><td>{fmt(d["mean"])}</td><td>{d["wins"]}/{d["ties"]}/{d["losses"]}</td></tr>'
    body+='</table><p>12题迁移为每类预先固定3题的开发诊断；不是独立确认性评价。Token为观测用量，不假定缓存折扣或未知费用。</p>'
    (OUT/'index.html').write_text(body,encoding='utf-8')
    print(json.dumps(dict(single_pass_dual=sum(r['score']['complete'] for r in sp),supplement_groups=len(supplement))))


if __name__=='__main__':run()
