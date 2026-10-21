"""Round2 receipt reparse, fixed EAS and predeclared clustered comparisons."""
import argparse
from collections import Counter
import csv
import statistics

from common import *

def analyze(gen,scoring,out):
    from chapter2_judge_200_rubric import requests,parse
    from chapter2_formal_scoring_200 import failed_generation,unidentified
    from chapter2_metric_revision_200 import graded_validity,valid_at_threshold
    from chapter2_model14b_analysis_200 import summarize,effect_intervals,holm,duplicate_input_stability
    from score_round2 import CONFIG,audit_generation
    p=read(CONFIG);completion=read(scoring/'completion.json')
    if out.exists():raise FileExistsError('fresh analysis directory required')
    if sha(Path(__file__))!=p['analysis_sha256'] or completion['execution_protocol_sha256']!=sha(CONFIG) or completion['sessions']!=1400:
        raise ValueError('analysis/completion binding drift')
    anns={a['id']:a for a in read(DATASET/'scoring/annotations.json')};ev=read(DATASET/'scoring/evidence.json')
    g=read(ARCHIVE/'configs/e2e_14b_v1.json');qs={q['id']:q['question'] for q in public_questions()}
    rows=[];receipts={};usage=Counter();request_statuses=Counter();unknown_usage=0;cache={}
    for arm in p['arms']:
        sealed=read(scoring/'sealed_arms'/(arm+'.json'))
        closed=read(scoring/'completed_arms'/(arm+'.json'))
        if sha(scoring/'sealed_arms'/(arm+'.json'))!=closed['sealed_arm_sha256']:raise ValueError('sealed arm drift')
        for s in sealed['rows']:
            qid=s['id'];key=f'{arm}/{qid}';folder=scoring/'sessions'/arm/qid;path=folder/'result.json';score=read(path)
            if sha(path)!=completion['results_sha256'][key] or sha(path)!=closed['results_sha256'][qid]:raise ValueError('score result drift')
            source=gen/arm/'generation'/qid/'result.json';r=read(source)
            if sha(source)!=s['generation_sha256'] or score['generation_sha256']!=sha(source) or score['execution_protocol_sha256']!=sha(CONFIG):raise ValueError('answer/score binding drift')
            audit_generation(source.parent,qs[qid],arm,g,cache)
            if s['generation_status']!='answered':reparsed=failed_generation(s['generation_status'])
            elif max(s['input_tokens'])>32768:reparsed=unidentified('judge_input_budget_exceeded_before_export')
            else:
                payloadpath=scoring/'payloads'/arm/(qid+'.json')
                if sha(payloadpath)!=s['payload_sha256']:raise ValueError('payload drift')
                payload=read(payloadpath);records=[]
                for i,req in enumerate(requests(payload)):
                    requestpath=folder/'requests'/f'{i:02d}.json';record=read(requestpath)
                    if record['request']!=req['body'] or record['endpoint']!=p['endpoint'] or record['model']!=p['model'] or record['status']=='in_flight':raise ValueError('judge request drift')
                    if record['transport_attempts']!=1 or record['content_retries']!=0:raise ValueError('judge retry drift')
                    usage.update({k:v for k,v in record.get('response',{}).get('usage',{}).items() if type(v)is int})
                    if not all(type(record.get('response',{}).get('usage',{}).get(k))is int for k in ['prompt_tokens','completion_tokens']):unknown_usage+=1
                    request_statuses[record['status']]+=1;receipts[f'{key}/{i:02d}']=sha(requestpath);records.append(record)
                reparsed=parse(records,payload)
                if 'metrics' not in reparsed:reparsed={**unidentified(reparsed.get('reason','unparseable')),**reparsed}
            if any(score.get(k)!=v for k,v in reparsed.items()):raise ValueError('frozen parser differs from saved score')
            a=anns[qid];m=score['metrics'];conditional=a['labels']['condition_discrimination'];app=m['applicability']
            ledger={(x['path'],x['line']) for x in r['delivered_lines']}
            full=[all((ev[eid]['path'],n) in ledger for n in range(ev[eid]['line_start'],ev[eid]['line_end']+1)) for eid in a['required_evidence_ids']]
            tools=Counter(e['name'] for e in r['tool_events'])
            row=dict(arm=arm,id=qid,group=a['split_group'],theme=a['theme_id'],
                type=('S' if a['labels']['evidence_integration']=='single' else 'M')+str(int(conditional)),conditional=conditional,
                cv_lower=m['complete_lower'],cv_upper=m['complete_upper'],coverage_lower=m['required_point_coverage_lower'],coverage_upper=m['required_point_coverage_upper'],
                condition_lower=int(app=='pass'),condition_upper=int(app in {'pass','unknown'}),factuality=m['factuality'],applicability=app,
                score_status=score['status'],score_reason=score.get('reason'),generation_status=r['status'],
                judge_payload_sha256=s.get('payload_sha256'),references_delivered=r.get('references_delivered'),reference_count=len(r.get('references')or[]),
                tool_calls=len(r['tool_events']),search_calls=tools['search'],delivered_lines=len(ledger),necessary_evidence_recall=sum(full)/len(full),
                complete_necessary_evidence=int(all(full)),input_tokens=r['counted_input_tokens'],completion_tokens=r['actual_completion_tokens'],
                physical_requests=len(r['turns']),characters=r['knowledge_characters'],seconds=r['seconds'])
            row['score_lower'],row['score_upper']=graded_validity(row)
            if valid_at_threshold(row,1)!=(row['cv_lower'],row['cv_upper']):raise ValueError('strict metric not reproduced')
            if r['status']!='answered' and (row['score_lower']or row['score_upper']):raise ValueError('failure earned score')
            rows.append(row)
    if len(rows)!=1400 or len({(r['arm'],r['id']) for r in rows})!=1400:raise ValueError('incomplete or duplicate grid')
    byarm={arm:sorted([r for r in rows if r['arm']==arm],key=lambda r:r['id']) for arm in p['arms']}
    comparisons={}
    for family,specs in p['statistics']['comparison_families'].items():
        values=[]
        for name in specs:
            arm=name.split(' vs ')[1];left=byarm['graph'];right=byarm[arm]
            if [r['id'] for r in left]!=[r['id'] for r in right]:raise ValueError('unpaired comparison')
            effect=effect_intervals([[r['score_lower'],r['score_upper']]for r in left],[[r['score_lower'],r['score_upper']]for r in right],[r['group'] for r in left])
            effect.update(comparison=name,practical_threshold=.05,practical_positive_identified=effect['difference_lower']>=.05)
            values.append(effect)
        for effect,adjusted in zip(values,holm([e['exact_cluster_sign_randomization_p_upper']for e in values])):
            effect.update(holm_p_upper=adjusted,statistical_positive_identified=effect['difference_lower']>0 and adjusted<.05)
        comparisons[family]=values
    summary=dict(schema='round2_e2e_analysis_v1',sessions=1400,question_count=200,knowledge_groups=24,
        generation_protocol_sha256=sha(ARCHIVE/'configs/e2e_14b_v1.json'),scoring_protocol_sha256=sha(CONFIG),
        scoring_completion_sha256=sha(scoring/'completion.json'),analysis_source_sha256=sha(Path(__file__)),
        by_arm={arm:summarize(rs)for arm,rs in byarm.items()},
        by_type={arm:{k:summarize([r for r in rs if r['type']==k])for k in ['S0','S1','M0','M1']}for arm,rs in byarm.items()},
        by_group={arm:{k:summarize([r for r in rs if r['group']==k])for k in sorted({r['group']for r in rs})}for arm,rs in byarm.items()},
        comparisons=comparisons,judge=dict(usage=dict(usage),unknown_usage_requests=unknown_usage,request_statuses=dict(request_statuses)),
        duplicate_packet_stability=duplicate_input_stability(rows),
        boundaries=['Exposed200 development bank; not new holdout or unseen generalization','Same exact14B model for anonymous answering/judging; synthetic calibration is not human accuracy',
            'No historical results rescored or pooled into new paired family','Whole-source delivery is not semantic citation entailment','One generation per method/question; clustered uncertainty is not repeat-run variance'])
    save(out/'summary.json',summary);save(out/'session-metrics.json',rows);save(out/'judge-request-bindings.json',receipts)
    with (out/'session-metrics.csv').open('x',encoding='utf-8-sig',newline='')as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    lines=['# 第二轮端到端问答结果','',f'1400会话，全部200题保留分母；生成/评分批次 `{gen.name}`。EAS为0–100分。','',
        '|方法|EAS下界|EAS上界|严格完整下界|严格完整上界|生成状态|评分状态|','|---|---:|---:|---:|---:|---|---|']
    for arm,v in summary['by_arm'].items():lines.append(f"|{arm}|{100*v['score_lower']:.2f}|{100*v['score_upper']:.2f}|{100*v['complete_lower']:.2f}%|{100*v['complete_upper']:.2f}%|{v['generation_statuses']}|{v['judge_statuses']}|")
    lines+=['','## 预定义配对比较','', '|比较族|比较|EAS差值识别范围|Holm p上界|正向统计支持|','|---|---|---:|---:|---|']
    for family,values in comparisons.items():
        for v in values:lines.append(f"|{family}|{v['comparison']}|[{100*v['difference_lower']:.2f}, {100*v['difference_upper']:.2f}]|{v['holm_p_upper']:.6g}|{v['statistical_positive_identified']}|")
    lines+=['','未知的识别区间与知识组bootstrap区间分开，主比较四项与消融两项分别校正。四类型仅描述。','',*summary['boundaries']]
    (out/'e2e_report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    (out/'analysis-source.py').write_bytes(Path(__file__).read_bytes())
    print('Scoring reparse and full200 paired analysis complete',flush=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--generation',type=Path,required=True);ap.add_argument('--scoring',type=Path,required=True);ap.add_argument('--output',type=Path,required=True)
    a=ap.parse_args();analyze(a.generation,a.scoring,a.output)
