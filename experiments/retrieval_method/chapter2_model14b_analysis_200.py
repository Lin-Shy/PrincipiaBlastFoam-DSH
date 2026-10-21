"""Reproducible full-bank statistics from immutable generation and score receipts."""
import argparse
from collections import Counter, defaultdict
from datetime import datetime,timedelta
import hashlib
import json
from pathlib import Path
import statistics
import numpy as np
from chapter2_optimization_200 import read,save,sha,DATASET,PROJECT,RESOURCES
from chapter2_judge_200_rubric import requests,parse
from chapter2_formal_scoring_200 import failed_generation,unidentified
from chapter2_metric_revision_200 import graded_validity,valid_at_threshold
from chapter2_model14b_generation_audit import audit_session

ARMS=['graph','bm25','e5','hybrid','none','graph_no_cross','graph_no_aliases']


def holm(values):
    order=sorted(range(len(values)),key=lambda i:values[i]);out=[0.]*len(values);previous=0.
    for j,i in enumerate(order):
        previous=max(previous,min(1.,(len(values)-j)*values[i]));out[i]=previous
    return out


def effect_intervals(left,right,groups,seed=20261019,replicates=10000):
    """Sharp marginal difference bounds and paired percentile cluster intervals."""
    labels=sorted(set(groups));membership=[np.array([g==label for g in groups]) for label in labels]
    lower=np.array(left)[:,0]-np.array(right)[:,1]
    upper=np.array(left)[:,1]-np.array(right)[:,0]
    sizes=np.array([m.sum() for m in membership]);lo=np.array([lower[m].sum() for m in membership]);hi=np.array([upper[m].sum() for m in membership])
    draws=np.random.default_rng(seed).integers(len(labels),size=(replicates,len(labels)))
    bootlo=lo[draws].sum(axis=1)/sizes[draws].sum(axis=1)
    boothi=hi[draws].sum(axis=1)/sizes[draws].sum(axis=1)
    observed=(float(lower.mean()),float(upper.mean()))
    min_abs=0 if observed[0]<=0<=observed[1] else min(abs(x) for x in observed)
    # For any admissible unknown completion, the observed statistic is at
    # least min_abs, while each sign statistic is no greater than this
    # interval's maximum absolute endpoint. Counting this superset yields a
    # conservative upper bound on its exact randomization p-value.
    if min_abs==0:pupper=1.
    else:
        count=0;total=1<<len(labels);bits=np.arange(len(labels),dtype=np.uint32)
        for start in range(0,total,65536):
            signs=1-2*((np.arange(start,min(start+65536,total),dtype=np.uint32)[:,None]>>bits)&1).astype(np.int8)
            low=np.where(signs>0,lo,-hi).sum(axis=1)/len(groups)
            high=np.where(signs>0,hi,-lo).sum(axis=1)/len(groups)
            count+=int((np.maximum(abs(low),abs(high))>=min_abs-1e-12).sum())
        pupper=count/total
    return dict(difference_lower=observed[0],difference_upper=observed[1],
        lower_endpoint_ci95=np.quantile(bootlo,[.025,.975]).tolist(),
        upper_endpoint_ci95=np.quantile(boothi,[.025,.975]).tolist(),
        uncertainty_envelope_ci95=[float(np.quantile(bootlo,.025)),float(np.quantile(boothi,.975))],
        exact_cluster_sign_randomization_p_upper=pupper,
        p_scope='Exact p when all outcomes identified; conservative p upper bound otherwise',
        macro_difference_lower=float(np.mean(lo/sizes)),macro_difference_upper=float(np.mean(hi/sizes)))


def original_summarize(rows):
    n=len(rows);conditional=[r for r in rows if r['conditional']]
    result=dict(n=n,complete_lower=sum(r['cv_lower'] for r in rows)/n,complete_upper=sum(r['cv_upper'] for r in rows)/n,
        complete_pass=sum(r['cv_lower'] for r in rows),complete_unknown=sum(r['cv_upper']-r['cv_lower'] for r in rows),
        coverage_lower=statistics.mean(r['coverage_lower'] for r in rows),coverage_upper=statistics.mean(r['coverage_upper'] for r in rows),
        condition_n=len(conditional),condition_lower=sum(r['condition_lower'] for r in conditional)/len(conditional) if conditional else None,
        condition_upper=sum(r['condition_upper'] for r in conditional)/len(conditional) if conditional else None,
        judge_statuses=dict(Counter(r['score_status'] for r in rows)),generation_statuses=dict(Counter(r['generation_status'] for r in rows)),
        factuality=dict(Counter(r['factuality'] for r in rows)),applicability=dict(Counter(r['applicability'] for r in conditional)),
        tool_sessions=sum(r['tool_calls']>0 for r in rows),tool_calls=sum(r['tool_calls'] for r in rows),
        search_sessions=sum(r['search_calls']>0 for r in rows),search_calls=sum(r['search_calls'] for r in rows),
        evidence_sessions=sum(r['delivered_lines']>0 for r in rows),
        necessary_evidence_recall=statistics.mean(r['necessary_evidence_recall'] for r in rows),
        complete_necessary_evidence_rate=statistics.mean(r['complete_necessary_evidence'] for r in rows),
        cited_sessions=sum(r['reference_count']>0 for r in rows),
        nonempty_delivered_citation_sessions=sum(r['reference_count']>0 and r['references_delivered'] is True for r in rows),
        undelivered_reference_sessions=sum(r['generation_status']=='answered' and r['references_delivered'] is False for r in rows),
        input_tokens=sum(r['input_tokens'] for r in rows),completion_tokens=sum(r['completion_tokens'] for r in rows),
        physical_requests=sum(r['physical_requests'] for r in rows),
        mean_characters=statistics.mean(r['characters'] for r in rows),
        mean_seconds=statistics.mean(r['seconds'] for r in rows),median_seconds=statistics.median(r['seconds'] for r in rows),
        p95_seconds=float(np.quantile([r['seconds'] for r in rows],.95)))
    groups=defaultdict(list)
    for row in rows:groups[row['group']].append(row)
    result['group_count']=len(groups)
    for key in ['cv_lower','cv_upper','coverage_lower','coverage_upper']:
        result['group_macro_'+key]=statistics.mean(statistics.mean(r[key] for r in group) for group in groups.values())
    return result


def summarize(rows):
    result=original_summarize(rows)
    for side in ['lower','upper']:
        result['score_'+side]=statistics.mean(r['score_'+side] for r in rows)
        groups=sorted({r['group'] for r in rows})
        result['group_macro_score_'+side]=statistics.mean(
            statistics.mean(r['score_'+side] for r in rows if r['group']==g) for g in groups)
    return result


def duplicate_input_stability(rows):
    """Exploratory repeatability only; never reconciles or changes scores."""
    groups=defaultdict(list)
    for row in rows:
        if row.get('judge_payload_sha256'):groups[row['judge_payload_sha256']].append(row)
    repeated=[group for group in groups.values() if len(group)>1]
    result=dict(scope='Post-hoc measurement diagnostic of byte-identical anonymous judge packets; not human accuracy; no rejudgment or score replacement',
        repeated_packet_groups=len(repeated),sessions_in_repeated_groups=sum(map(len,repeated)),
        all_pairs=0,complete_bounds_discordant_pairs=0,determinate_complete_comparable_pairs=0,
        determinate_complete_discordant_pairs=0,metric_vector_discordant_pairs=0)
    fields=['cv_lower','cv_upper','coverage_lower','coverage_upper','condition_lower','condition_upper','factuality','applicability']
    for group in repeated:
        for i,left in enumerate(group):
            for right in group[i+1:]:
                result['all_pairs']+=1
                result['complete_bounds_discordant_pairs']+=int((left['cv_lower'],left['cv_upper'])!=(right['cv_lower'],right['cv_upper']))
                comparable=left['cv_lower']==left['cv_upper'] and right['cv_lower']==right['cv_upper']
                result['determinate_complete_comparable_pairs']+=int(comparable)
                result['determinate_complete_discordant_pairs']+=int(comparable and left['cv_lower']!=right['cv_lower'])
                result['metric_vector_discordant_pairs']+=int(any(left[field]!=right[field] for field in fields))
    return result


def main(root,scoring,output):
    if output.exists():raise FileExistsError(output)
    completion=read(scoring/'completion.json');protocol=read(scoring/'protocol.json')
    if completion['sessions']!=1400 or completion['execution_protocol_sha256']!=sha(scoring/'protocol.json'):raise ValueError('Incomplete scoring')
    scorer=Path(__file__).with_name('chapter2_formal_scoring_200.py')
    if sha(scorer)!=protocol['driver_sha256']:raise ValueError('Scoring driver drift')
    for rel,digest in protocol['frozen_implementation_sha256'].items():
        if sha(PROJECT/rel)!=digest:raise ValueError('Scorer source drift')
    formal=read(root/'protocol.json')
    for arm,digest in formal['graphs'].items():
        if sha(root/'graphs'/(arm+'.json'))!=digest:raise ValueError('Frozen graph drift')
    for name,digest in formal['e5_resources'].items():
        if sha(RESOURCES/'e5'/name)!=digest:raise ValueError('Frozen E5 resource drift')
    for name,digest in formal['scoring_data_sha256'].items():
        if sha(DATASET/'scoring'/name)!=digest:raise ValueError('Scoring annotation drift')
    calibration=Path(formal['judge']['calibration'])
    if sha(calibration/'completion.json')!=formal['judge']['calibration_completion_sha256']:raise ValueError('Calibration drift')
    endpoints={read(path)['endpoint'] for path in (calibration/'sessions').glob('*/requests/*.json')}
    if len(endpoints)!=1:raise ValueError('Ambiguous calibrated endpoint')
    expected_endpoint=next(iter(endpoints))
    anns={r['id']:r for r in read(DATASET/'scoring/annotations.json')};evidence=read(DATASET/'scoring/evidence.json')
    rows=[];requests_count=Counter();unknown_reasons=Counter();usages=Counter();records_bindings={};all_times=[]
    fresh_protocol=protocol
    if formal['answer_model']!='qwen3-14b' or formal['baseline_reuse'] is not False:
        raise ValueError('A fresh full-grid 14B experiment is required')
    combined=[(r,False) for r in fresh_protocol['sessions']]
    cache={};reused_generation_audit={};batch_requests=defaultdict(Counter)
    for session,reused in combined:
        protocol=fresh_protocol
        completion=read(scoring/'completion.json')
        score_root=scoring
        generation_root=root
        arm,qid=session['arm'],session['id'];key=f'{arm}/{qid}'
        folder=score_root/'sessions'/arm/qid;result_path=folder/'result.json';score=read(result_path)
        if sha(result_path)!=completion['results_sha256'][key]:raise ValueError('Score receipt drift')
        genpath=generation_root/'generation'/arm/qid/'result.json';gen=read(genpath)
        if sha(genpath)!=session['generation_sha256']:raise ValueError('Generation drift')
        expected_execution=sha(scoring/'protocol.json')
        if score['execution_protocol_sha256']!=expected_execution or score['generation_sha256']!=sha(genpath):
            raise ValueError('Score execution identity drift')
        verified=audit_session(root,arm,qid,next(q['question'] for q in read(root/'public-questions.json') if q['id']==qid),formal,cache)
        if verified['result_sha256']!=session['generation_sha256']:
            raise ValueError('Generation request/source audit drift')
        if session['generation_status']!='answered':reparsed=failed_generation(session['generation_status'])
        elif max(session['input_tokens'])>protocol['input_tokens_per_request']:reparsed=unidentified('judge_input_budget_exceeded_before_export')
        else:
            payload_path=score_root/'payloads'/arm/(qid+'.json')
            if sha(payload_path)!=session['payload_sha256']:raise ValueError('Payload drift')
            payload=read(payload_path);reqs=requests(payload);records=[]
            for i,req in enumerate(reqs):
                path=folder/'requests'/f'{i:02d}.json';record=read(path)
                if record['request']!=req['body'] or record['status']=='in_flight':raise ValueError('Request binding/unclosed')
                raw=json.dumps(record['request'],ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
                if hashlib.sha256(raw).hexdigest()!=record['request_sha256']:raise ValueError('Request fingerprint drift')
                if record['model']!='qwen3-14b' or record['provider']!='qwen_proxy' or record['endpoint']!=expected_endpoint or record['transport_attempts']!=1 or record['content_retries']!=0:raise ValueError('Deployment drift')
                requests_count[record['status']]+=1;batch_requests['reused' if reused else 'fresh'][record['status']]+=1
                for name,value in record.get('response',{}).get('usage',{}).items():
                    if type(value)is int:usages[name]+=value
                records_bindings[f'{key}/{i:02d}']=sha(path);records.append(record)
                all_times.append((record['started_utc'],record['seconds']))
            reparsed=parse(records,payload)
            if 'metrics' not in reparsed:reparsed={**unidentified(reparsed.get('reason','unparseable')),**reparsed}
        if any(score.get(k)!=v for k,v in reparsed.items()):raise ValueError('Stored score differs from frozen parser')
        if score['status']!='judged':unknown_reasons[score.get('reason',score['status'])]+=1
        a=anns[qid];m=score['metrics'];conditional=a['labels']['condition_discrimination'];app=m['applicability']
        ledger={(r['path'],r['line']) for r in gen['delivered_lines']}
        covered=[]
        for eid in a['required_evidence_ids']:
            e=evidence[eid];covered.append(all((e['path'],n) in ledger for n in range(e['line_start'],e['line_end']+1)))
        t=Counter(e['name'] for e in gen['tool_events'])
        rows.append(dict(arm=arm,id=qid,reused=reused,source_generation_protocol_sha256=gen['protocol_sha256'],source_scoring_protocol_sha256=expected_execution,group=a['split_group'],theme=a['theme_id'],
            judge_payload_sha256=session.get('payload_sha256'),
            type=('S' if a['labels']['evidence_integration']=='single' else 'M')+str(int(conditional)),conditional=conditional,
            cv_lower=m['complete_lower'],cv_upper=m['complete_upper'],coverage_lower=m['required_point_coverage_lower'],coverage_upper=m['required_point_coverage_upper'],
            condition_lower=int(app=='pass'),condition_upper=int(app in {'pass','unknown'}),
            applicability=app,factuality=m['factuality'],score_status=score['status'],score_reason=score.get('reason'),
            generation_status=gen['status'],references_delivered=gen.get('references_delivered'),reference_count=len(gen.get('references') or []),
            tool_calls=len(gen['tool_events']),search_calls=t['search'],delivered_lines=len(ledger),
            necessary_evidence_recall=sum(covered)/len(covered),complete_necessary_evidence=int(all(covered)),
            input_tokens=gen['counted_input_tokens'],completion_tokens=gen['actual_completion_tokens'],
            physical_requests=len(gen['turns']),characters=gen['knowledge_characters'],seconds=gen['seconds']))
    protocol=fresh_protocol
    for row in rows:
        row['score_lower'],row['score_upper']=graded_validity(row)
        if valid_at_threshold(row,1)!=(row['cv_lower'],row['cv_upper']):
            raise ValueError('Original strict metric not recovered')
        if row['generation_status']!='answered' and (row['score_lower'] or row['score_upper']):
            raise ValueError('Failed generation earned score')
    save(output/'reused-generation-audit.json',dict(sessions=len(reused_generation_audit),bindings=reused_generation_audit))
    rows.sort(key=lambda r:(ARMS.index(r['arm']),r['id']))
    assert len(rows)==len({(r['arm'],r['id']) for r in rows})==1400
    all_arms={arm:summarize([r for r in rows if r['arm']==arm]) for arm in ARMS}
    types={arm:{kind:summarize([r for r in rows if r['arm']==arm and r['type']==kind]) for kind in ['S0','S1','M0','M1']} for arm in ARMS}
    groups={arm:{group:summarize([r for r in rows if r['arm']==arm and r['group']==group]) for group in sorted({r['group'] for r in rows})} for arm in ARMS}
    byarm={arm:sorted([r for r in rows if r['arm']==arm],key=lambda r:r['id']) for arm in ARMS}
    comparisons={}
    for family,others in [('primary',['bm25','e5','hybrid','none']),('ablation',['graph_no_cross','graph_no_aliases'])]:
        values=[]
        for arm in others:
            left=byarm['graph'];right=byarm[arm]
            assert [r['id'] for r in left]==[r['id'] for r in right]
            value=effect_intervals([[r['score_lower'],r['score_upper']] for r in left],[[r['score_lower'],r['score_upper']] for r in right],[r['group'] for r in left])
            value.update(comparison='graph vs '+arm,practical_threshold=.05)
            value['practical_positive_identified']=value['difference_lower']>=.05
            values.append(value)
        adjusted=holm([v['exact_cluster_sign_randomization_p_upper'] for v in values])
        for value,padj in zip(values,adjusted):
            value['holm_p_upper']=padj
            value['statistical_positive_identified']=value['difference_lower']>0 and padj<.05
        comparisons[family]=values
    expected_requests=sum(len(r.get('input_tokens',[])) for r,_ in combined if max(r.get('input_tokens',[0]))<=32768)
    if sum(requests_count.values())!=expected_requests:raise ValueError('Incomplete judge request receipts')
    timeline=[]
    for timestamp,seconds in all_times:
        started=datetime.fromisoformat(timestamp);timeline.extend([(started,1),(started+timedelta(seconds=seconds),-1)])
    active=peak=0
    for _,delta in sorted(timeline):active+=delta;peak=max(peak,active)
    if active!=0 or protocol['workers']!=16:raise ValueError('Judge worker accounting drift')
    # started_utc uses the wall clock; seconds uses time.monotonic(). Adding
    # them does not reconstruct an exact end timestamp when the wall clock
    # changes. Keep this diagnostic, but use the frozen executor's 16 workers
    # and sequential calls per worker as the actual concurrency bound.
    graph=read(root/'graphs/selected.json')
    resource_sizes=dict(graph_json_bytes={arm:(root/'graphs'/(arm+'.json')).stat().st_size for arm in formal['graphs']},
        e5_vector_bytes=(RESOURCES/'e5/embeddings.npy').stat().st_size,e5_passage_metadata_bytes=(RESOURCES/'e5/passages.json').stat().st_size,
        e5_passage_count=len(read(RESOURCES/'e5/passages.json')),graph_nodes=len(graph['nodes']),graph_edges=len(graph['edges']),
        source_units=len(graph['units']),source_files=len(graph['source_hashes']),source_alias_units=graph['bilingual_alias_revision']['source_units_with_aliases'],
        source_aliases=graph['bilingual_alias_revision']['aliases_added'],
        scope='Uncompressed serialized artifacts only; not RAM, model weights or total preparation cost. Session timing excludes backend initialization.')
    result=dict(schema='formal_200_answer14b_analysis_v1',answer_model='qwen3-14b',judge_same_model_as_answer=True,question_count=200,knowledge_groups=24,registered_sessions=1400,
        formal_protocol_sha256=sha(root/'protocol.json'),scoring_protocol_sha256=sha(scoring/'protocol.json'),
        scoring_completion_sha256=sha(scoring/'completion.json'),generation_audit_sha256=sha(root/'generation-audit.json'),
        input_scoring_sha256={n:sha(DATASET/'scoring'/n) for n in ['annotations.json','evidence.json']},
        analysis_source_sha256=sha(Path(__file__)),
        primary_metric='end_to_end_valid_answer_score',secondary_metric='complete_valid_answer_rate',
        metric_formula='100 * mean(required_point_coverage * factuality_gate * applicability_gate)',
        execution_batches=dict(fresh_sessions=1400,reused_baseline_sessions=0,
            judge_requests={k:dict(v) for k,v in batch_requests.items()},
            limitations='All seven 14B arms are fresh, same experiment batch. API latency is descriptive, not a controlled backend speed test. 8B remains under its original batch identities.'),
        metric_adoption='Metric and accepted official graph fixed before the full 14B run; selected after prior 8B results. Frozen rubric unchanged.',by_arm=all_arms,by_type=types,by_group=groups,comparisons=comparisons,
        judge_repeated_input_stability=duplicate_input_stability(rows),
        resource_artifacts=resource_sizes,
        judge=dict(request_statuses=dict(requests_count),usage=dict(usages),nonfullyjudged_reasons=dict(unknown_reasons),
            endpoint=expected_endpoint,executor_concurrency_bound=protocol['workers'],
            mixed_clock_interval_overlap_diagnostic=peak,
            concurrency_scope='Frozen 16-worker executor, sequential requests per worker; mixed wall/monotonic receipt intervals are not exact request end timestamps',
            approximate_wall_seconds=(max(t for t,_ in timeline)-min(t for t,_ in timeline)).total_seconds()),
        boundaries=['Graph and metric selected after prior 8B results; fixed before this fresh all-seven-arms 14B run',
            'Same exposed benchmark as method development; no unseen-generalization inference',
            'AI scoring and synthetic calibration are not human truth or independent judge accuracy',
            'Answer and judge both use qwen3-14b in independent anonymous requests; shared-model bias may affect model-scale comparisons',
            'Citation metric checks actual source delivery, not semantic entailment',
            'Evidence metrics evaluate actual whole-system delivered gold line spans, not fixed-query backend recall or rank metrics',
            'Generation failures are retained as zero; unknown judgments retain lower and upper bounds',
            'Single stochastic generation per question/arm; cluster intervals do not measure run-to-run model variation'])
    save(output/'summary.json',result);save(output/'session-metrics.json',rows);save(output/'judge-request-bindings.json',records_bindings)
    helper=Path(__file__).with_name('chapter2_model14b_generation_audit.py')
    (output/'generation-audit-helper-source.py').write_bytes(helper.read_bytes())
    save(output/'support-sources.json',dict(
        generation_audit_helper_sha256=sha(helper),scoring_driver_sha256=sha(scorer),
        metric_source_sha256=sha(Path(__file__).with_name('chapter2_metric_revision_200.py'))))
    source=output/'analysis-source.py';source.write_bytes(Path(__file__).read_bytes())
    with (output/'session-metrics.csv').open('x',encoding='utf-8-sig',newline='') as f:
        import csv
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    fields=['n','score_lower','score_upper','group_macro_score_lower','group_macro_score_upper','complete_lower','complete_upper','coverage_lower','coverage_upper','condition_n','condition_lower','condition_upper',
        'group_macro_cv_lower','group_macro_cv_upper','tool_sessions','tool_calls','necessary_evidence_recall','complete_necessary_evidence_rate',
        'nonempty_delivered_citation_sessions','input_tokens','completion_tokens','physical_requests','mean_characters','mean_seconds','p95_seconds']
    summary_rows=[]
    for arm in ARMS:
        for scope,layer in [('all',{'all':all_arms[arm]}),('type',types[arm]),('knowledge_group',groups[arm])]:
            for name,value in layer.items():summary_rows.append(dict(scope=scope,arm=arm,stratum=name,**{field:value[field] for field in fields}))
    with (output/'summary-metrics.csv').open('x',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=['scope','arm','stratum',*fields]);writer.writeheader();writer.writerows(summary_rows)
    print(json.dumps({arm:{k:v[k] for k in ['score_lower','score_upper','complete_lower','complete_upper','coverage_lower','coverage_upper','condition_lower','condition_upper']} for arm,v in all_arms.items()}),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True);p.add_argument('--scoring',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();main(a.root,a.scoring,a.output)
