"""Complete-cohort development report and actual physical-request accounting."""
import argparse
from collections import Counter,defaultdict
from datetime import datetime
from pathlib import Path
import sys

PROJECT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(PROJECT/'src'))
from chapter2_v2_retrieval_probe import read,save,sha
from chapter2_v2_metric_diagnosis import macro
from chapter2_knowledge_evaluation import evidence_coverage,primary_bounds


def physical_requests(activity):
    counts=Counter();tokens=Counter();missing=Counter();events=defaultdict(list)
    bindings={}
    for path in sorted((activity/'development').glob('**/requests/*.json')):
        row=read(path)
        if 'started_utc' not in row:continue
        stage=path.relative_to(activity/'development').parts[0]
        counts[stage]+=1;bindings[path.relative_to(activity).as_posix()]=sha(path)
        payload=row.get('raw_response')
        usage=payload.get('usage',{}).get('total_tokens') if isinstance(payload,dict) else None
        if type(usage) is int and usage>=0:tokens[stage]+=usage
        else:missing[stage]+=1
        seconds=row.get('seconds')
        if isinstance(seconds,(int,float)):
            start=datetime.fromisoformat(row['started_utc']).timestamp()
            events[(stage,row['model'])].extend([(start,1),(start+seconds,-1)])
    # Connectivity receipts have a different directory depth, intentionally
    # enumerated separately rather than guessed as QA requests.
    for path in sorted((activity/'development/proxy_preflight_001').glob('*/*.json')):
        row=read(path)
        if 'started_utc' not in row:continue
        stage='proxy_preflight_001';counts[stage]+=1
        payload=row.get('raw_response')
        usage=payload.get('usage',{}).get('total_tokens') if isinstance(payload,dict) else None
        if type(usage) is int and usage>=0:tokens[stage]+=usage
        else:missing[stage]+=1
        bindings[path.relative_to(activity).as_posix()]=sha(path)
    for path in sorted((activity/'diagnosis/evaluation_only').glob('**/responses/*.json')):
        row=read(path)
        if 'events' not in row:continue
        stage='offline/'+path.relative_to(activity/'diagnosis/evaluation_only').parts[0]
        bindings[path.relative_to(activity).as_posix()]=sha(path)
        for event in row['events']:
            counts[stage]+=1
            usage=event.get('usage',{}).get('total_tokens')
            if type(usage) is int and usage>=0:tokens[stage]+=usage
            else:missing[stage]+=1
    peaks={}
    for (stage,model),timeline in events.items():
        active=peak=0
        for _,delta in sorted(timeline):active+=delta;peak=max(peak,active)
        peaks[stage+'/'+model]=peak
    return dict(scope='Physical Qwen development receipts and recorded offline source-review transport events; reused references excluded.',physical_requests_by_stage=dict(counts),known_total_tokens_by_stage=dict(tokens),
        missing_usage_by_stage=dict(missing),timestamp_overlap_estimate_peak=peaks,
        physical_request_file_sha256=bindings,
        limitations=['UTC start plus monotonic duration is only a timestamp-overlap estimate, not a measured concurrent-request count or GPU utilization.',
            'Clock resolution can make known-sequential calls overlap by milliseconds. The scheduler independently bounds each model to sixteen sequential-call workers.',
            'Missing usage remains unknown; offline host analysis and hardware/electricity/monetary costs are unmetered.'])


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('activity','generation','scores','dataset','output'):p.add_argument('--'+name,type=Path,required=True)
    a=p.parse_args();protocol=read(a.generation/'protocol.json');completion=read(a.generation/'completion.json')
    sc=read(a.scores/'completion.json');sp=read(a.scores/'protocol.json')
    if not completion['complete'] or not sc['complete'] or sp['generation_protocol_sha256']!=sha(a.generation/'protocol.json'):
        raise ValueError('Complete bound generation and scoring required')
    annotations={r['id']:r for r in read(a.dataset/'scoring/annotations.json')}
    evidence=read(a.dataset/'scoring/evidence.json')
    if sp['annotations_sha256']!=sha(a.dataset/'scoring/annotations.json') or sp['evidence_sha256']!=sha(a.dataset/'scoring/evidence.json'):
        raise ValueError('Score-side frozen evidence changed')
    rows=[];series={}
    for model in protocol['models']:
        for method in protocol['methods']:
            cohort=[]
            for qid in protocol['question_ids']:
                rp=a.generation/'sessions'/model/method/qid/'result.json';result=read(rp)
                path=a.scores/'sessions'/model/method/qid/'score.json';score=read(path)
                if score['result_sha256']!=sha(rp) or result['protocol_sha256']!=sha(a.generation/'protocol.json'):
                    raise ValueError('Score or generation binding changed')
                metrics=score.get('metrics',{})
                failure=result['status']!='answered'
                coverage=[metrics.get('required_point_coverage_lower',0),metrics.get('required_point_coverage_upper',1)] if not failure else [0,0]
                factual=metrics.get('factuality','unknown')
                condition=metrics.get('applicability','unknown')
                ev=evidence_coverage(result,annotations[qid],evidence)
                row=dict(question_id=qid,group=annotations[qid]['split_group'],model=model,method=method,
                    generation_status=result['status'],judge_status=score['status'],
                    primary_bounds=list(primary_bounds(score)),coverage_bounds=coverage,
                    factual_bounds=[0,0] if failure else [int(factual=='pass'),int(factual!='fail')],
                    conditional_bounds=([0,0] if failure else [int(condition=='pass'),int(condition!='fail')])
                        if annotations[qid]['labels']['condition_discrimination'] else None,
                    necessary_evidence=ev,references_delivered=result.get('references_delivered'),
                    result_sha256=sha(rp),score_sha256=sha(path))
                rows.append(row);cohort.append(row)
            series[model+'/'+method]=dict(planned_questions=len(cohort),
                strict_complete=macro(cohort,lambda r:r['primary_bounds']),
                required_point_coverage=macro(cohort,lambda r:r['coverage_bounds']),
                end_to_end_factual_acceptability=macro(cohort,lambda r:r['factual_bounds']),
                conditional_answer_acceptability=macro(cohort,lambda r:r['conditional_bounds']),
                delivered_necessary_evidence_recall=macro(cohort,lambda r:[r['necessary_evidence']['necessary_evidence_recall']]*2),
                delivered_complete_evidence=macro(cohort,lambda r:[r['necessary_evidence']['complete_necessary_evidence']]*2),
                generation_status=dict(Counter(r['generation_status'] for r in cohort)),
                judge_status=dict(Counter(r['judge_status'] for r in cohort)))
    cost=physical_requests(a.activity)
    if completion['completed']!=len(rows) or sc['completed']!=len(rows):raise ValueError('Planned denominator changed')
    revision=read(a.dataset/'revision.json') if (a.dataset/'revision.json').exists() else None
    value=dict(schema='matched_qa_development_summary_v2',formal_result=False,development_only=True,
        rubric_revision=revision,
        generation_protocol_sha256=sha(a.generation/'protocol.json'),scoring_protocol_sha256=sha(a.scores/'protocol.json'),
        planned_sessions=len(rows),completed_generation=len(rows),completed_scores=len(rows),
        series=series,rows=rows,costs=cost,
        limitations=['All questions are development items; repeated tuning prevents confirmatory claims.',
            'AI v7 judge algorithm retained; independent human validity is not established. Rubric scope is separately identified by rubric_revision.',
            'Coverage, factual acceptability, condition acceptability, source delivery and strict complete success are distinct metrics.',
            'The shared answer checklist and output limit differ from the historical run; only current arms are matched.',
            'No scores are scaled to a desired percentage, no failed/unknown item is removed.',
            'New independently registered validation and all required controls are needed before replacing paper results.'])
    save(a.output,value)
    for name,entry in series.items():
        print(name,{k:[round(v*100,2) for v in entry[k]['bounds']] for k in ('strict_complete','required_point_coverage','delivered_necessary_evidence_recall')},flush=True)


if __name__=='__main__':main()
