"""Whole-activity physical costs, separate from formal answer metrics."""
import argparse
from collections import Counter,defaultdict
from datetime import datetime,timezone
import hashlib
import json
import math
from pathlib import Path


def read(path):return json.loads(path.read_text(encoding='utf-8'))
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def measurements(row):
    """One measurement per actual attempt; never charge a response twice."""
    if row.get('provider')=='qwen_proxy':
        if row.get('transport_attempts')!=1 or row.get('content_retries')!=0:
            raise ValueError('Expected recorded single-attempt proxy receipt')
        payload=row.get('raw_response')
        usage=payload.get('usage') if isinstance(payload,dict) else row.get('usage')
        return [dict(model=row['model'],status=row['status'],seconds=row.get('seconds'),usage=usage)]
    if row.get('request',{}).get('model')=='deepseek-flash':
        events=row.get('events')
        if not isinstance(events,list) or not events:raise ValueError('Offline physical events required')
        if [e.get('attempt') for e in events]!=list(range(1,len(events)+1)):
            raise ValueError('Offline attempt identity changed')
        return [dict(model='deepseek-flash',status=e['status'],seconds=e.get('seconds'),usage=e.get('usage')) for e in events]
    raise ValueError('Unknown physical receipt format')


def summarize(rows):
    known_usage=known_time=prompt=completion=0;seconds=0.0
    for row in rows:
        usage=row['usage']
        if isinstance(usage,dict) and all(type(usage.get(k)) is int and usage[k]>=0 for k in ['prompt_tokens','completion_tokens']):
            known_usage+=1;prompt+=usage['prompt_tokens'];completion+=usage['completion_tokens']
        duration=row['seconds']
        if duration is not None:
            if type(duration) not in [int,float] or not math.isfinite(duration) or duration<0:raise ValueError('Invalid duration')
            known_time+=1;seconds+=duration
    return dict(physical_attempts=len(rows),statuses=dict(Counter(r['status'] for r in rows)),models=dict(Counter(r['model'] for r in rows)),
                usage_known_attempts=known_usage,usage_unknown_attempts=len(rows)-known_usage,
                known_prompt_tokens=prompt,known_completion_tokens=completion,
                duration_known_attempts=known_time,duration_unknown_attempts=len(rows)-known_time,sum_known_request_seconds=seconds,
                money_cost=None,host_ai_cost=None,hardware_cost=None)


def stage(path,root):
    parts=path.relative_to(root).parts
    if parts[0]=='diagnosis':
        if parts[1].startswith('proxy_'):return 'operational_probes'
        if parts[1]=='evaluation_only' and path.parent.name=='responses':return 'offline_semantic_audit'
    if parts[0]=='development':
        if parts[1]=='qa_001':return 'development_generation'
        if parts[1].startswith('qa_001_scores'):return 'development_grading'
        if parts[1].startswith('proxy_'):return 'operational_probes'
    if parts[0]=='formal':
        if parts[1]=='generation_001':
            return 'formal_complete_material_generation' if len(parts)>2 and parts[2]=='complete_material' else 'formal_generation'
        if parts[1].startswith('proxy_'):return 'operational_probes'
        if (path.parent.parent/'score.json').exists():return 'formal_grading'
    raise ValueError('Unclassified physical receipt: '+path.relative_to(root).as_posix())


def audit(root,allow_inflight=False):
    root=Path(root);paths=set()
    for top in ['development','formal','diagnosis']:
        if (root/top).exists():paths.update((root/top).rglob('requests/*.json'))
    for folder in (root/'diagnosis').glob('proxy_*'):
        paths.update(folder.rglob('request.json'))
    for name in ['verify.json','necessity.json']:
        paths.update((root/'diagnosis/evaluation_only').rglob('responses/'+name))
    stages=defaultdict(list);inventory={};live=[];copies=[]
    for path in sorted(paths):
        relative=path.relative_to(root);parts=relative.parts
        if len(parts)>1 and parts[0]=='development' and parts[1].startswith('qa_001_scores_continued_'):
            original=root/'development/qa_001_scores'/Path(*parts[2:])
            if original.exists():
                if sha(original)!=sha(path):raise ValueError('Conflicting copied development receipt')
                copies.append(dict(copy=relative.as_posix(),original=original.relative_to(root).as_posix(),sha256=sha(path)));continue
        data=path.read_bytes();row=json.loads(data);current=stage(path,root)
        if row.get('status')=='in_flight':
            if not allow_inflight:raise ValueError('Live request prevents complete cost accounting')
            live.append(relative.as_posix());continue
        physical=measurements(row)
        if any(r['status']=='in_flight' for r in physical):raise ValueError('Live offline event')
        stages[current].extend(physical)
        inventory[relative.as_posix()]=dict(sha256=hashlib.sha256(data).hexdigest(),stage=current,physical_attempts=len(physical))
    return dict(schema='whole_activity_physical_costs_v1',created_utc=datetime.now(timezone.utc).isoformat(),formal_quality_result=False,
                model_calls=0,quality_labels_used=False,snapshot_only=allow_inflight,
                stages={k:summarize(v) for k,v in sorted(stages.items())},total=summarize([r for rows in stages.values() for r in rows]),
                canonical_receipts=inventory,in_flight_receipts_excluded=live,byte_identical_copied_receipts_not_recharged=copies,
                limits=['Request seconds are sums of physical durations, not wall-clock task latency or GPU utilization.',
                        'Missing usage/time remain unknown; no frozen tariff or bill is available.',
                        'Only canonical development/formal/diagnostic receipt locations are counted; archives, setup and audit copies are excluded.',
                        'Inherited construction, host AI, hardware and electricity costs are unmeasured.',
                        'Costs from predecessor activities, including reused semantic audits and graph artifacts, are outside this current-directory inventory.',
                        'A live snapshot cannot prove full-activity completion. New physical receipt locations must be classified explicitly.'])


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--allow-inflight',action='store_true');args=p.parse_args()
    if args.output.exists():raise FileExistsError('New immutable cost audit required')
    value=audit(args.root,args.allow_inflight);args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x',encoding='utf-8') as f:json.dump(value,f,ensure_ascii=False,indent=2)
    print(dict(total=value['total'],stages={k:v['physical_attempts'] for k,v in value['stages'].items()},inflight_excluded=len(value['in_flight_receipts_excluded'])))


if __name__=='__main__':main()
