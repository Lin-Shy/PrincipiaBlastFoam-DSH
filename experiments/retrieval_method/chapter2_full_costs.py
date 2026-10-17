"""Physical single-attempt proxy receipts; unknown usage never becomes zero."""
from collections import Counter, defaultdict
from datetime import datetime
import math

from chapter2_v2_retrieval_probe import read, sha


def physical_cost(paths):
    signatures=set();files={};statuses=Counter();models=Counter();timeline=defaultdict(list)
    prompt=completion=unknown=0;seconds=0.0;duplicates=0;collisions=0
    for path in paths:
        path=path.resolve()
        if str(path) in files:duplicates+=1;continue
        row=read(path)
        if row.get('status')=='in_flight':raise ValueError('A live physical request is not a terminal cost')
        if row.get('provider')!='qwen_proxy' or row.get('transport_attempts')!=1 or row.get('content_retries')!=0:
            raise ValueError('Single-attempt proxy provenance required')
        start=datetime.fromisoformat(row['started_utc']).timestamp();duration=row.get('seconds')
        if isinstance(duration,bool) or not isinstance(duration,(int,float)) or not math.isfinite(duration) or duration<0:
            raise ValueError('Known terminal request duration required')
        identity=(row['endpoint'],row['model'],row['request_sha256'],row['started_utc'])
        files[str(path)]=sha(path)
        # Windows wall-clock resolution can give genuinely distinct concurrent
        # calls identical body/model/start tuples. Exclusive canonical receipt
        # paths identify attempts; never collapse calls on a timestamp heuristic.
        if identity in signatures:collisions+=1
        signatures.add(identity);statuses[row['status']]+=1;models[row['model']]+=1;seconds+=duration
        usage=row.get('raw_response',{}).get('usage',{}) if isinstance(row.get('raw_response'),dict) else {}
        if all(type(usage.get(k)) is int and usage[k]>=0 for k in ('prompt_tokens','completion_tokens')):
            prompt+=usage['prompt_tokens'];completion+=usage['completion_tokens']
        else:unknown+=1
        timeline[row['model']].extend([(start,1),(start+duration,-1)])
    peaks={}
    for model,events in timeline.items():
        active=peak=0
        for _,delta in sorted(events):active+=delta;peak=max(peak,active)
        peaks[model]=peak
    return dict(physical_attempts=len(files),usage_known_attempts=len(files)-unknown,usage_unknown_attempts=unknown,
        known_prompt_tokens=prompt,known_completion_tokens=completion,known_total_tokens=prompt+completion,
        sum_physical_request_seconds=seconds,statuses=dict(statuses),models=dict(models),
        timestamp_overlap_estimate_peak=peaks,repeated_canonical_paths_not_recharged=duplicates,
        timestamp_identity_collisions_retained=collisions,request_files_sha256=files,
        money_cost=None,hardware_cost=None,host_ai_cost=None,
        limits=['Timestamp overlap is an estimate, not a measured service concurrency or GPU utilization.',
            'Unknown usage remains unknown; no frozen monetary tariff or provider bill.',
            'Inputs must be canonical physical receipt paths, excluding copied archives. Equal timestamps and request hashes do not prove duplicate calls.',
            'Host AI, hardware, electricity and inherited graph construction costs are not measured by these receipts.'])
