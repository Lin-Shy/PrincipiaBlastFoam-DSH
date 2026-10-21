"""Physical request accounting for recorded development activity."""
from collections import Counter, defaultdict
from datetime import datetime
import hashlib
import json

def read(p): return json.loads(p.read_text(encoding="utf-8"))
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()

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
