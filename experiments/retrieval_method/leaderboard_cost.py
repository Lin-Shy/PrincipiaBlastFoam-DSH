"""按官方峰谷价重建已报告用量的费用区间；未知尝试和账单总额不置零。"""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime,timezone
from pathlib import Path
import leaderboard_audit as audit


def peak(seconds):
    d=datetime.fromtimestamp(seconds,timezone.utc)
    return d.weekday()<5 and (1<=d.hour<4 or 6<=d.hour<10)


def price(usage,event,spec):
    keys=['prompt_cache_hit_tokens','prompt_cache_miss_tokens','completion_tokens']
    if not isinstance(usage,dict) or any(type(usage.get(k)) is not int or usage[k]<0 for k in keys):return None
    if usage.get('prompt_tokens')!=usage[keys[0]]+usage[keys[1]] or usage.get('total_tokens')!=usage['prompt_tokens']+usage[keys[2]]:return None
    start=event.get('started_unix_ns');duration=event.get('seconds')
    tiers={'peak','off_peak'}
    if type(start) is int and isinstance(duration,(int,float)) and duration>=0:
        first=start/1e9;last=first+duration
        if first<datetime.fromisoformat(spec['effective_utc']).timestamp():return None
        # Endpoint and every hourly boundary capture any tier transition during the request.
        points=[first,last,*range((int(first)//3600+1)*3600,int(last)+1,3600)]
        tiers={'peak' if peak(t) else 'off_peak' for t in points}
    values=[sum(usage[k]*spec['usd_per_million'][tier][k]/1e6 for k in keys) for tier in tiers]
    return min(values),max(values)


def stage(root,spec,seen_attempts=None):
    usage=Counter();statuses=Counter();models=Counter();unpriced_models=Counter();unpriced_reasons=Counter()
    lower=upper=0.;known=unknown=0;duplicates=0;bindings={}
    # Only request records in session directories; inherited semantic references are not copied/recounted.
    folders=[*root.glob('sessions/*'),*root.glob('*/sessions/*')]
    for folder in folders:
        for path in folder.glob('*.json'):
            record=audit.read(path)
            if 'request_sha256' not in record:continue
            bindings[str(path.relative_to(root))]=audit.sha(path)
            model=record.get('request',{}).get('model');models[model]+=1
            for index,event in enumerate(record.get('events',[])):
                identity=(record['request_sha256'],event.get('started_unix_ns'),index)
                if seen_attempts is not None:
                    if identity in seen_attempts:duplicates+=1;continue
                    seen_attempts.add(identity)
                statuses[event['status']]+=1
                tokens=event.get('usage')
                if tokens is None and event['status']=='response':tokens=record.get('raw_response',{}).get('usage')
                if isinstance(tokens,dict):usage.update({k:v for k,v in tokens.items() if isinstance(v,int)})
                amount=price(tokens,event,spec) if model==spec['model'] else None
                if amount is None:
                    unknown+=1
                    if model!=spec['model']:
                        unpriced_models[str(model)]+=1
                        unpriced_reasons['model_outside_flash_scope']+=1
                    elif not isinstance(tokens,dict):unpriced_reasons['usage_missing']+=1
                    else:unpriced_reasons['usage_or_time_not_priceable']+=1
                else:known+=1;lower+=amount[0];upper+=amount[1]
    return {'reported_usage':dict(usage),'attempt_statuses':dict(statuses),'models':dict(models),
            'priced_attempts':known,'unpriced_attempts':unknown,'duplicate_inherited_attempts_excluded':duplicates,
            'unpriced_attempt_models':dict(unpriced_models),'unpriced_reason_counts':dict(unpriced_reasons),
            'reported_usage_usd_interval':[lower,upper] if known else None,
            'actual_invoice_cost_usd':None,'all_attempts_reconstructed_usd_interval':[lower,upper] if known and not unknown else None,
            'request_file_sha256':bindings}


def graphify_stage(root,spec):
    usage=Counter();models=Counter();unpriced_models=Counter();unpriced_reasons=Counter()
    lower=upper=0.;known=unknown=0;bindings={}
    for path in (root/'http').glob('*.json'):
        record=audit.read(path);bindings[path.name]=audit.sha(path)
        tokens=record.get('usage')
        if isinstance(tokens,dict):usage.update({k:v for k,v in tokens.items() if isinstance(v,int)})
        event={'started_unix_ns':int(datetime.fromisoformat(record['started_at']).timestamp()*1e9),
               'seconds':record.get('elapsed_seconds')}
        model=record.get('request',{}).get('model');models[model]+=1
        amount=price(tokens,event,spec) if model==spec['model'] else None
        if amount is None:
            unknown+=1
            if model!=spec['model']:
                unpriced_models[str(model)]+=1
                unpriced_reasons['model_outside_flash_scope']+=1
            elif not isinstance(tokens,dict):unpriced_reasons['usage_missing']+=1
            else:unpriced_reasons['usage_or_time_not_priceable']+=1
        else:known+=1;lower+=amount[0];upper+=amount[1]
    summary=audit.read(root/'costs.json')
    if dict(usage)!=summary['reported_usage_sum']:raise ValueError('Graphify original usage ledger differs from summary')
    return {'source':str(root),'cost_summary_sha256':audit.sha(root/'costs.json'),
            'reported_usage':dict(usage),'models':dict(models),'priced_attempts':known,'unpriced_attempts':unknown,
            'unpriced_attempt_models':dict(unpriced_models),'unpriced_reason_counts':dict(unpriced_reasons),
            'reported_usage_usd_interval':[lower,upper] if known else None,'actual_invoice_cost_usd':None,
            'all_attempts_reconstructed_usd_interval':[lower,upper] if known and not unknown else None,
            'elapsed_seconds':summary.get('elapsed_seconds'),'request_file_sha256':bindings}


def main():
    cli=argparse.ArgumentParser(description=__doc__);cli.add_argument('--root',type=Path,required=True)
    cli.add_argument('--prices',type=Path,required=True);cli.add_argument('--output',type=Path,required=True);a=cli.parse_args()
    root=a.root.resolve();spec=audit.read(a.prices)
    roots={f'qa/{p.name}':p for p in (root/'runs').iterdir() if p.is_dir() and (p/'protocol.json').exists()}
    roots.update({f'review/{p.name}':p for p in (root/'reviews').iterdir() if p.is_dir()})
    candidate_root=root/'candidate'
    if candidate_root.is_dir():
        roots.update({f'construction/{p.name}':p for p in candidate_root.iterdir() if p.is_dir() and p.name.startswith('semantics')})
    result={'schema':'reported-usage-official-price-reconstruction-v1','prices':spec,'price_spec_sha256':audit.sha(a.prices),
            'stages':{name:stage(p,spec) for name,p in roots.items()},
            'note':'Amounts reconstruct only exact deepseek-flash request records at the documented Flash public USD rates, not an account invoice. Historical calls under another model are explicitly outside this Flash pricing scope. Unknown, interrupted, failed and in-flight usage cannot be priced as zero. A request spanning a tier boundary has a range because provider billing-time attribution is unobserved.'}
    # A repaired run may inherit successful and interrupted request records. Count each
    # physical attempt only once in the overall ledger while preserving per-run lifecycle views.
    seen=set();unique=[stage(p,spec,seen) for p in roots.values()]
    amounts=[v['reported_usage_usd_interval'] for v in unique if v['reported_usage_usd_interval']]
    other_model=sum(v['unpriced_reason_counts'].get('model_outside_flash_scope',0) for v in unique)
    unpriced_flash=sum(v['unpriced_attempts']-v['unpriced_reason_counts'].get('model_outside_flash_scope',0) for v in unique)
    result['unique_flash_experiment_attempts']={'priced_attempts':sum(v['priced_attempts'] for v in unique),
        'unpriced_flash_attempts':unpriced_flash,
        'historical_other_model_attempts_excluded':other_model,
        'inherited_duplicates_excluded':sum(v['duplicate_inherited_attempts_excluded'] for v in unique),
        'reported_usage_usd_interval':[sum(v[i] for v in amounts) for i in (0,1)] if amounts else None,
        'actual_invoice_cost_usd':None,
        'identity':'request SHA + original attempt start nanoseconds + attempt index; per-run stage views may overlap and must not be summed',
        'scope':'Only exact deepseek-flash attempts enter this total. Retained historical construction attempts from other models remain provenance and are explicitly excluded.'}
    review_seen=set()
    unique_reviews=[stage(path,spec,review_seen) for name,path in roots.items() if name.startswith('review/')]
    review_amounts=[value['reported_usage_usd_interval'] for value in unique_reviews
                    if value['reported_usage_usd_interval']]
    result['unique_review_attempts']={
        'reported_usage':dict(sum((Counter(value['reported_usage']) for value in unique_reviews),Counter())),
        'priced_attempts':sum(value['priced_attempts'] for value in unique_reviews),
        'unpriced_attempts':sum(value['unpriced_attempts'] for value in unique_reviews),
        'inherited_duplicates_excluded':sum(value['duplicate_inherited_attempts_excluded'] for value in unique_reviews),
        'reported_usage_usd_interval':([sum(value[index] for value in review_amounts) for index in (0,1)]
                                       if review_amounts else None),
        'actual_invoice_cost_usd':None,
        'identity':'request SHA + original attempt start nanoseconds + attempt index; copied recovery records count once',
    }
    baseline=root.parent/'graphify_baseline_v1'
    original={}
    if baseline.is_dir():
        for arm in ['native','text_adapter']:
            for folder in sorted((baseline/arm/'attempts').glob('*')):
                if (folder/'costs.json').exists():original[arm+'/'+folder.name]=graphify_stage(folder,spec)
            folder=baseline/arm/'presentation'
            if (folder/'costs.json').exists():original[arm+'/presentation']=graphify_stage(folder,spec)
    result['original_graphify_build_stages']=original
    structure=root.parent/'graphify_structure_v1/builds/004'
    accounting=structure/'accounting.json'
    result['deterministic_structure_build']=({'source':str(structure),'accounting_sha256':audit.sha(accounting),
        'accounting':audit.read(accounting),
        'scope':'Incremental deterministic GN/GH construction has zero model calls; inherited Graphify parent construction is not free and is reported separately. Hardware/electricity and unmetered I/O costs remain unobserved.'}
        if accounting.exists() else None)
    audit.save(a.output,result)
    print({k:{f:v[f] for f in ['priced_attempts','unpriced_attempts','reported_usage_usd_interval']} for k,v in result['stages'].items()})


if __name__=='__main__':main()
