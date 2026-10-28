"""Build full-denominator retrieval and Agentic pairing reports."""
import csv,json,statistics
from pathlib import Path
import single_pass_dev40 as s

def mean(v): return statistics.mean(v) if v else None
def numbers(rows,key):
    out=[]
    for r in rows:
        try: out.append(float(r[key]))
        except (ValueError,TypeError,KeyError): pass
    return out
def run():
    from judge_contract import joint_metrics
    qs=s.load(s.QUESTIONS); annotations={x['id']:x for x in s.load(s.SPLIT/'gold/dev40/annotations.json')};gold=s.load(s.SPLIT/'gold/dev40/evidence.json')
    typefile=s.WORKSPACE/'graduation-datasets/chapter02_knowledge_qa/formal_v2_200/questions.csv'
    types={x['id']:x['type'] for x in csv.DictReader(typefile.open(encoding='utf-8-sig'))}
    old=list(csv.DictReader((s.RUN/'experiments/agentic/dev40/results/scores.csv').open(encoding='utf-8-sig')))
    oldmap={}
    for r in old:
        if r['method'] in s.METHODS and r['judge_record_present']=='True': oldmap.setdefault((r['model'],r['method'],r['question_id']),[]).append(r)
    packet_items=s.load(s.OUT/'scoring/packet.json')['items'];packet_map={(x['model'],x['method'],x['qid']):x['item'] for x in packet_items}
    output=[];summary=[];typesummary=[];retrieval=[]
    for model in s.MODELS:
      oldmodel=model
      for method in s.METHODS:
       rows=[]
       for q in qs:
        folder=s.OUT/'generation'/f'{method}__{model}'/q['id'];recovery=s.latest_recovery(f'{method}__{model}',q['id'])
        rawpath=recovery/'result.json' if (recovery/'result.json').exists() else folder/'result.json';raw=s.load(rawpath)
        rp=recovery/'retrieval.json' if (recovery/'retrieval.json').exists() else folder/'retrieval.json';ret=s.load(rp) if rp.exists() else {}
        got={(z['path'],z['line']) for z in ret.get('delivered_lines',[])};needed=set()
        for eid in annotations[q['id']]['required_evidence_ids']:
            e=gold[eid];needed.update((e['path'],n) for n in range(e['line_start'],e['line_end']+1))
        recall=len(got&needed)/len(needed) if needed else None
        # Generation errors receive zero on the fixed denominator; no judge calls are fabricated.
        item=packet_map[(model,method,q['id'])];per_judge={};judge={}
        for j in s.JUDGES:
         p=s.OUT/'scoring'/j/item['sample_id']/'parsed.json'
         if p.exists():
          judge[j]=s.load(p)['record'];per_judge[j]=joint_metrics(judge[j],[c['criterion_id'] for c in item['criteria']],item['conditional'],raw.get('generation_failed',False))
        keys=('K','F','A','EAS_arith','EAS_geo')
        if raw.get('generation_failed'):sm={'K':None,'F':None,'A':None,'EAS_arith':0.0,'EAS_geo':0.0}
        elif set(per_judge)==set(s.JUDGES):
         sm={k:mean([per_judge[j][k] for j in s.JUDGES if isinstance(per_judge[j].get(k),(int,float))]) for k in keys}
        else:sm={k:None for k in keys}
        agent=oldmap.get((oldmodel,method,q['id']),[])
        am={k:mean(numbers(agent,k)) for k in sm}
        row=dict(model=model,method=method,question_id=q['id'],type=types.get(q['id']),single_pass_status=raw.get('status'),generation_failed=raw.get('generation_failed'),answer=raw.get('answer',''),model_usage=raw.get('usage'),generation_seconds=raw.get('seconds'),retrieval_calls=ret.get('backend_calls',0),retrieval_characters=ret.get('delivered_characters',0),necessary_evidence_line_recall=recall,complete_required_evidence=bool(needed) and needed<=got,single_pass_metrics=sm,judge_records=judge,agentic_metrics=am,delta={k:(sm[k]-am[k] if sm[k] is not None and am[k] is not None else None) for k in sm},agentic_judged_observations=len(agent))
        output.append(row);rows.append(row)
       dual=sum(len(r['judge_records'])==2 for r in rows)
       usage_rows=[r['model_usage'] or {} for r in rows]
       paired=[r for r in rows if len(r['judge_records'])==2 and r['agentic_judged_observations']>=2]
       summary.append(dict(model=model,method=method,n=40,successful_generations=sum(not r['generation_failed'] for r in rows),generation_failures=sum(r['generation_failed'] for r in rows),dual_scored=sum(len(r['judge_records'])==2 for r in rows),paired_answer_count=len(paired),paired_delta={k:mean([r['delta'][k] for r in paired if r['delta'][k] is not None]) for k in ('K','F','A','EAS_arith','EAS_geo')},paired_agentic_means={k:mean([r['agentic_metrics'][k] for r in paired if r['agentic_metrics'][k] is not None]) for k in ('K','F','A','EAS_arith','EAS_geo')},mean_retrieval_characters=mean([r['retrieval_characters'] for r in rows]),mean_necessary_evidence_line_recall=mean([r['necessary_evidence_line_recall'] for r in rows if r['necessary_evidence_line_recall'] is not None]),complete_required_evidence=sum(r['complete_required_evidence'] for r in rows),model_prompt_tokens_total=sum(u.get('prompt_tokens',0) for u in usage_rows),model_completion_tokens_total=sum(u.get('completion_tokens',0) for u in usage_rows),mean_generation_seconds=mean([r['generation_seconds'] for r in rows if r['generation_seconds'] is not None]),single_pass_means={k:mean([r['single_pass_metrics'][k] for r in rows if r['single_pass_metrics'][k] is not None]) for k in ('K','F','A','EAS_arith','EAS_geo')},agentic_means={k:mean([r['agentic_metrics'][k] for r in rows if r['agentic_metrics'][k] is not None]) for k in ('K','F','A','EAS_arith','EAS_geo')}))
       for typ in ('S0','S1','M0','M1'):
        tr=[r for r in rows if r['type']==typ]
        tp=[r for r in tr if len(r['judge_records'])==2 and r['agentic_judged_observations']>=2]
        typesummary.append(dict(model=model,method=method,type=typ,n=len(tr),successful_generations=sum(not r['generation_failed'] for r in tr),dual_scored=sum(len(r['judge_records'])==2 for r in tr),paired_answer_count=len(tp),single_pass_EAS_arith=mean([r['single_pass_metrics']['EAS_arith'] for r in tr if r['single_pass_metrics']['EAS_arith'] is not None]),agentic_EAS_arith_on_paired=mean([r['agentic_metrics']['EAS_arith'] for r in tp if r['agentic_metrics']['EAS_arith'] is not None]),paired_delta_EAS_arith=mean([r['delta']['EAS_arith'] for r in tp if r['delta']['EAS_arith'] is not None])))
        retrieval.append(dict(model=model,method=method,retrieval_call_count=sum(r['retrieval_calls'] for r in rows),retrieval_chars_total=sum(r['retrieval_characters'] for r in rows),generation_api_attempts=sum(any((s.OUT/'generation_recovery'/f'{method}__{model}'/q['id']/a/'model_requests'/'00.json').exists() for a in ('attempt_2','attempt_3','attempt_4')) or (s.OUT/'generation'/f'{method}__{model}'/q['id']/'model_requests'/'00.json').exists() for q in qs),generation_successes=sum(r['single_pass_status']=='success' for r in rows),generation_failures=sum(r['generation_failed'] for r in rows)))
    judge_counts={j:sum(j in r['judge_records'] for r in output) for j in s.JUDGES}
    s.save(s.OUT/'analysis/per_answer_paired.json',output);s.save(s.OUT/'analysis/aggregate_paired.json',dict(aggregates=summary,by_type=typesummary,usage=retrieval,judge_requests_sent={j:len(list((s.OUT/'scoring'/j).glob('*/request.json'))) for j in s.JUDGES},judge_valid_records=judge_counts,test160_started=False,interpretation='Quality aggregates include only answers with both valid judge records; generation failures contribute zero EAS on the fixed denominator. Unscored answers remain missing, never imputed.'))
    fields=['model','method','question_id','type','single_pass_status','necessary_evidence_line_recall','complete_required_evidence','single_pass_K','single_pass_F','single_pass_A','single_pass_EAS_arith','single_pass_EAS_geo','agentic_K','agentic_F','agentic_A','agentic_EAS_arith','agentic_EAS_geo','delta_K','delta_F','delta_A','delta_EAS_arith','delta_EAS_geo','generation_seconds','retrieval_characters','model_usage','judge_names']
    with (s.OUT/'analysis/paired_comparison.csv').open('w',encoding='utf-8-sig',newline='') as f:
      w=csv.DictWriter(f,fieldnames=fields);w.writeheader()
      for r in output:
       row={k:r.get(k) for k in fields if k in r};row['judge_names']=';'.join(sorted(r['judge_records']))
       for key,vals in [('single_pass',r['single_pass_metrics']),('agentic',r['agentic_metrics']),('delta',r['delta'])]:
        for metric,value in vals.items():row[f'{key}_{metric}']=value
       w.writerow(row)
    print(json.dumps(dict(rows=len(output),groups=len(summary),out=str(s.OUT/'analysis/aggregate_paired.json'))))
if __name__=='__main__':run()
