"""严格准入的统一总榜汇总：完整网格、来源审阅、原始响应身份、事实家族区间。"""
from __future__ import annotations
import argparse
from collections import Counter,defaultdict
import copy
import json
from pathlib import Path
import random
import statistics

import leaderboard_audit as audit
import leaderboard_admission as admission
import leaderboard_review as review
import navigation_qa as qa


def terminal_failure(folder):
    """Only frozen, exhausted transport attempts are tested terminal failures; missing work stays null."""
    for p in sorted(folder.glob('*.json')):
        d=audit.read(p)
        if 'request_sha256' not in d or d.get('status')=='response':continue
        events=d.get('events',[])
        if d.get('status')=='invalid_response':
            return {'reason':'invalid_provider_response','request_file':p.name,'sha256':audit.sha(p)}
        if d.get('status')=='transport_error' and (len(events)>=9 or any(e.get('http_status') in [400,401,402,403] for e in events)):
            return {'reason':'frozen_transport_policy_exhausted','request_file':p.name,'sha256':audit.sha(p),'attempts':len(events)}
    return None


def validate_review(root,review_root,compiled):
    binding=compiled['binding'];folder=root/binding['arm']/'sessions'/binding['session']
    packet_path=review_root/'packets'/f"{compiled['blind_id']}.json"
    if audit.sha(folder/'result.json')!=binding['result_sha256'] or audit.sha(packet_path)!=binding['packet_sha256'] or audit.sha(root/'protocol.json')!=binding['protocol_sha256']:
        raise ValueError('review input binding drift')
    if audit.sha(review_root/'protocol.json')!=compiled['review_protocol_sha256']:
        raise ValueError('review protocol drift')
    p=audit.read(packet_path);r=audit.read(folder/'result.json');decisions=[];responses=[]
    for i in range(1,compiled['review_count']+1):
        response_path=review_root/'sessions'/compiled['blind_id']/f'review-{i}.json'
        response=audit.read(response_path);choice=qa.choice(response)
        if choice.get('finish_reason')!='stop':raise ValueError('truncated review cannot be ranked')
        decisions.append(review.materialize(qa.decode_json_prefix(choice['message']['content']),p,r))
        responses.append(audit.sha(response_path))
    if len(decisions) not in (2,3):raise ValueError('double source review missing')
    if len(decisions)==2 and (any(v['uncertain'] for _,v in decisions) or review.rating(decisions[0][1])!=review.rating(decisions[1][1])):
        raise ValueError('unadjudicated review disagreement')
    m,d=decisions[-1]
    if d!=compiled['decision']:raise ValueError('compiled decision differs from frozen reviewer response')
    if d['uncertain']:return None,responses
    quality={k:m[k] for k in ['answer_accuracy','qa_success','first_answer_success',*d['dimensions']]}
    if quality!=compiled['quality']:raise ValueError('compiled score differs from frozen scoring rules')
    return quality,responses


def validate_adjudication(root, review_root, adjudication_root, compiled):
    """Recompute scores from original source-unit decisions, never trust compiled scores."""
    import leaderboard_adjudication as adj
    protocol=audit.read(adjudication_root/'protocol.json')
    if audit.sha(adjudication_root/'protocol.json')!=compiled['adjudication_protocol_sha256']:
        raise ValueError('adjudication protocol drift')
    if protocol['parent_review_protocol_sha256']!=audit.sha(review_root/'protocol.json'):
        raise ValueError('adjudication parent drift')
    for name,h in protocol['files'].items():
        if audit.sha(adjudication_root/name)!=h:raise ValueError('adjudication source drift')
    binding=compiled['binding'];bid=compiled['blind_id']
    packet_path=review_root/'packets'/f'{bid}.json'
    result_path=root/binding['arm']/'sessions'/binding['session']/'result.json'
    if audit.sha(result_path)!=binding['result_sha256'] or audit.sha(packet_path)!=binding['packet_sha256'] or audit.sha(root/'protocol.json')!=binding['protocol_sha256']:
        raise ValueError('adjudication input drift')
    # Valid regular reviews are final; a correction must not overwrite them.
    regular=review_root/'sessions'/bid/'compiled.json'
    if regular.exists() and audit.read(regular)['status']=='reviewed':
        raise ValueError('adjudication cannot replace valid regular review')
    for name,h in compiled['selection']['parent_response_sha256'].items():
        if audit.sha(review_root/'sessions'/bid/name)!=h:raise ValueError('selection evidence drift')
    if protocol.get('prior_adjudication'):
        prior=Path(protocol['prior_adjudication'])
        if audit.sha(prior/'protocol.json')!=protocol['prior_protocol_sha256']:raise ValueError('prior correction drift')
        prior_compiled=prior/'sessions'/bid/'compiled.json'
        if prior_compiled.exists() and audit.read(prior_compiled)['status']=='reviewed':raise ValueError('cannot retry valid adjudication')
        for name,h in compiled['selection'].get('prior_response_sha256',{}).items():
            if audit.sha(prior/'sessions'/bid/name)!=h:raise ValueError('prior correction response drift')
    for prior in adj.prior_chain(protocol):
        prior_compiled=prior/'sessions'/bid/'compiled.json'
        if prior_compiled.exists() and audit.read(prior_compiled)['status']=='reviewed':raise ValueError('cannot retry valid ancestor adjudication')
        for name,h in compiled['selection'].get('prior_responses',{}).get(str(prior),{}).items():
            if audit.sha(prior/'sessions'/bid/name)!=h:raise ValueError('ancestor response drift')
    packet=audit.read(packet_path);result=audit.read(result_path);support=adj.units(result['seen_lines'])
    if qa.digest(qa.wire(support))!=compiled['support_units_sha256']:raise ValueError('support units drift')
    decisions=[];hashes=[]
    for i in range(1,compiled['adjudication_count']+1):
        path=adjudication_root/'sessions'/bid/f'adjudicate-{i}.json'
        choice=qa.choice(audit.read(path))
        if choice.get('finish_reason')!='stop':raise ValueError('truncated adjudication')
        hashes.append(audit.sha(path))
        accepted=compiled.get('accepted_response_files',[f'adjudicate-{j}.json' for j in range(1,compiled['adjudication_count']+1)])[i-1]
        if accepted!=path.name:
            if accepted!=f'correction-{i}.json':raise ValueError('unexpected correction response identity')
            try:review.materialize(adj.convert(qa.decode_json_prefix(choice['message']['content']),support),packet,result)
            except (ValueError,KeyError,TypeError):pass
            else:raise ValueError('valid adjudication was impermissibly corrected')
            corrected=path.parent/accepted;choice=qa.choice(audit.read(corrected));hashes.append(audit.sha(corrected))
            if choice.get('finish_reason')!='stop':raise ValueError('truncated correction')
        decisions.append(review.materialize(adj.convert(qa.decode_json_prefix(choice['message']['content']),support),packet,result))
    if hashes!=compiled['response_sha256'] or len(decisions) not in (2,3):raise ValueError('adjudication responses changed')
    if len(decisions)==2 and (any(d['uncertain'] for _,d in decisions) or review.rating(decisions[0][1])!=review.rating(decisions[1][1])):
        raise ValueError('adjudication disagreement unresolved')
    m,d=decisions[-1]
    quality=None if d['uncertain'] else {k:m[k] for k in ['answer_accuracy','qa_success','first_answer_success',*d['dimensions']]}
    if d!=compiled['decision'] or quality!=compiled['quality']:raise ValueError('adjudication score drift')
    return quality,hashes


def adjudication_lineages(adjudication_roots):
    """Expand newest-to-oldest correction chains and verify every parent edge."""
    expanded=[];seen=set();lineage=0
    for supplied in reversed(tuple(adjudication_roots)):
        current=Path(supplied).resolve();chain=[]
        while current not in seen:
            protocol=audit.read(current/'protocol.json')
            chain.append(current);seen.add(current)
            prior=protocol.get('prior_adjudication')
            if not prior:break
            parent=Path(prior).resolve()
            if audit.sha(parent/'protocol.json')!=protocol['prior_protocol_sha256']:
                raise ValueError('prior adjudication drift')
            current=parent
        if chain:
            expanded.extend((root,lineage) for root in chain);lineage+=1
    return expanded


def interval(values,seed=20260910,repeats=4000):
    if not values:return None
    rng=random.Random(seed);bootstrap=[statistics.mean(rng.choices(values,k=len(values))) for _ in range(repeats)]
    return [audit.percentile(bootstrap,.025),audit.percentile(bootstrap,.975)]


def assemble(root,review_root,output,adjudication_roots=()):
    protocol=audit.verify(root);review_protocol=audit.read(review_root/'protocol.json')
    for name,expected in review_protocol['files'].items():
        if audit.sha(review_root/name)!=expected:raise ValueError('frozen review code changed')
    # Computation must use the same metric and materialization code as the original review.
    for name in ['navigation_metrics.py','leaderboard_review.py','navigation_qa.py']:
        if audit.sha(Path(__file__).with_name(name))!=review_protocol['files'][name]:
            raise ValueError('active scoring implementation differs from frozen review: '+name)
    anchor=next(iter(protocol['groups']))
    questions=audit.read(root/anchor/'questions.json');annotations={a['id']:a for a in audit.read(root/anchor/'evaluation_only/annotations.json')}
    compiled={}
    for p in (review_root/'sessions').glob('*/compiled.json'):
        d=audit.read(p);key=(d['binding']['arm'],d['binding']['session'])
        if key in compiled:raise ValueError('duplicate compiled review')
        compiled[key]=d
    adjudicated={};adjudication_lineage={}
    for ar,lineage in adjudication_lineages(adjudication_roots):
        for path in (ar/'sessions').glob('*/compiled.json'):
            d=audit.read(path);key=(d['binding']['arm'],d['binding']['session'])
            if key in adjudicated:
                if adjudication_lineage[key]!=lineage:raise ValueError('duplicate source adjudications outside one correction lineage')
                continue
            adjudicated[key]=(ar,d)
            adjudication_lineage[key]=lineage
    rows=[];families={};all_models=Counter();all_fingerprints=Counter()
    for group,methods in protocol['groups'].items():
        for method in methods:
            sessions=[]
            for q in questions:
                for rep in range(1,protocol['replicates']+1):
                    name=f"{q['id']}--{method}--r{rep}";folder=root/group/'sessions'/name
                    cost=audit.ledger(folder);all_models.update(cost['provider_models']);all_fingerprints.update(cost['provider_fingerprints'])
                    quality=None;review_hashes=[];terminal=None;state='not_run'
                    if (folder/'result.json').exists():
                        result=audit.read(folder/'result.json')
                        if (result['id'],result['item_id'],result['method'],result['replicate'],result['question'])!=(q['id'],q['item_id'],method,rep,q['question']):raise ValueError('QA identity changed')
                        state='unreviewed_answer'
                        c=compiled.get((group,name))
                        if c:
                            quality,review_hashes=validate_review(root,review_root,c)
                            state='reviewed' if quality else 'unresolved_review'
                        if quality is None and (group,name) in adjudicated:
                            ar,c=adjudicated[group,name]
                            quality,review_hashes=validate_adjudication(root,review_root,ar,c)
                            state='reviewed' if quality else 'unresolved_review'
                    else:
                        terminal=terminal_failure(folder)
                        if terminal:state='tested_terminal_failure';quality={'qa_success':False}
                        elif folder.exists():state='unfinished_attempt'
                    sessions.append({'session':name,'question_id':q['id'],'family':q['item_id'],'replicate':rep,
                                     'category':annotations[q['item_id']]['category'],'state':state,'quality':quality,
                                     'review_response_sha256':review_hashes,'terminal_failure':terminal,'cost':cost})
            ready=all(s['quality'] is not None for s in sessions)
            row={'arm':group,'method':method,'expected':len(sessions),'states':dict(Counter(s['state'] for s in sessions)),
                 'rankable':ready,'strict_success_macro':None,'strict_success_95ci':None,'metrics':None,'sessions':sessions}
            if ready:
                family_values=defaultdict(list);category_values=defaultdict(list)
                for s in sessions:
                    family_values[s['family']].append(int(s['quality']['qa_success']))
                    category_values[s['category']].append(int(s['quality']['qa_success']))
                fm={f:statistics.mean(v) for f,v in family_values.items()};families[group,method]=fm
                row['strict_success_macro']=statistics.mean(statistics.mean(v) for v in category_values.values())
                row['strict_success_95ci']=interval(list(fm.values()))
                keys=set().union(*(s['quality'].keys() for s in sessions))
                metrics={}
                for k in sorted(keys):
                    bycat={}
                    for category in category_values:
                        values=[s['quality'].get(k) for s in sessions if s['category']==category and s['quality'].get(k) is not None]
                        bycat[category]={'mean':statistics.mean(values) if values else None,'applicable_count':len(values)}
                    means=[v['mean'] for v in bycat.values() if v['mean'] is not None]
                    metrics[k]={'macro_over_applicable_categories':statistics.mean(means) if means else None,'by_category':bycat}
                row['metrics']=metrics
                pairs=defaultdict(list)
                for s in sessions:pairs[s['family'],s['replicate']].append(bool(s['quality']['qa_success']))
                row['both_paraphrases_success_rate']=statistics.mean(all(v) for v in pairs.values())
                row['all_six_sessions_success_family_rate']=statistics.mean(all(v) for v in family_values.values())
            rows.append(row)
    replay_admission=admission.check(root)
    identity_ok=set(all_models)=={protocol['model']} and len(all_fingerprints)==1 and 'not_reported' not in all_fingerprints
    pairs=[]
    for i,a in enumerate(rows):
        for b in rows[i+1:]:
            ka=(a['arm'],a['method']);kb=(b['arm'],b['method'])
            if ka in families and kb in families:
                if families[ka].keys()!=families[kb].keys():raise ValueError('paired family grid mismatch')
                diffs=[families[ka][f]-families[kb][f] for f in sorted(families[ka])]
                pairs.append({'first':list(ka),'second':list(kb),'difference':statistics.mean(diffs),'paired_family_95ci':interval(diffs)})
    result={'schema':'leaderboard-quality-v1','protocol_sha256':audit.sha(root/'protocol.json'),
            'all_arms_rankable':replay_admission['passed'] and identity_ok and all(r['rankable'] for r in rows),'replay_and_budget_admission':replay_admission,'model_identity_compatible':identity_ok,
            'provider_models':dict(all_models),'provider_fingerprints':dict(all_fingerprints),'arms':rows,'paired_comparisons':pairs,
            'ranking':sorted([{'arm':r['arm'],'method':r['method'],'score':r['strict_success_macro']} for r in rows if r['rankable']],key=lambda r:-r['score']) if replay_admission['passed'] and identity_ok and all(r['rankable'] for r in rows) else None,
            'uncertainty':'18 fact-family resampling; paraphrases and repetitions remain within family. Same model family judge, not independent-human validation.',
            'missing_policy':'unrun/unreviewed remain null; only exhausted frozen provider failures count as observed strict failure. Non-answer citation/content submetrics remain not applicable, never invented.',
            'comparison_scope':'whole-system comparison; causal component claims require ablations'}
    audit.save(output,result)
    print(qa.wire({'all_arms_rankable':result['all_arms_rankable'],'rankable_arms':sum(r['rankable'] for r in rows),'reviewed_sessions':sum(r['states'].get('reviewed',0) for r in rows)}))
    return result


if __name__=='__main__':
    cli=argparse.ArgumentParser(description=__doc__);cli.add_argument('--run',type=Path,required=True)
    cli.add_argument('--adjudications',type=Path,action='append',default=[]);cli.add_argument('--reviews',type=Path,required=True);cli.add_argument('--output',type=Path,required=True);a=cli.parse_args()
    assemble(a.run.resolve(),a.reviews.resolve(),a.output.resolve(),[p.resolve() for p in a.adjudications])
