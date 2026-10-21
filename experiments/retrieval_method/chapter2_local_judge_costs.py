"""本地单次请求账本的物理成本；不把缺失用量或机器成本计作零。"""
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
from chapter2_local_score_interruption import has_unknown_interruption_duration


def physical_local_cost(paths):
    seen_paths=set();seen_attempts={};files=[];attempts=unknown=duplicates=prompt=completion=0
    seconds=0.0;duration_unknown=0
    for path in paths:
        path=Path(path).resolve()
        if path in seen_paths:continue
        seen_paths.add(path);raw=path.read_bytes();record=json.loads(raw)
        if record.get('provider')!='qwen_local' or record.get('transport_attempts')!=1:
            raise ValueError('Not a local single-attempt ledger')
        if record.get('status') in {'prepared','in_flight'}:
            raise ValueError('Unresolved local attempt cannot be reported as terminal')
        started=record.get('started_utc')
        if not isinstance(started,str) or datetime.fromisoformat(started).tzinfo is None:
            raise ValueError('Local physical attempt timestamp missing')
        body=record.get('request')
        fingerprint=hashlib.sha256(json.dumps(body,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        if fingerprint!=record.get('request_sha256') or not record.get('endpoint'):
            raise ValueError('Local physical request identity mismatch')
        identity=(record['endpoint'],fingerprint,started)
        if identity in seen_attempts:
            if seen_attempts[identity]!=record:raise ValueError('Conflicting copies of a local attempt')
            duplicates+=1
        else:
            seen_attempts[identity]=record;attempts+=1
            duration=record.get('seconds')
            if has_unknown_interruption_duration(record):
                duration_unknown+=1
            elif type(duration) not in (float,int) or not math.isfinite(duration) or duration<0:
                raise ValueError('Local physical request duration missing')
            else: seconds+=duration
            response=record.get('raw_response')
            usage=response.get('usage') if isinstance(response,dict) else None
            known=isinstance(usage,dict) and all(type(usage.get(k)) is int and usage[k]>=0 for k in ['prompt_tokens','completion_tokens'])
            if known:
                prompt+=usage['prompt_tokens'];completion+=usage['completion_tokens']
            else:unknown+=1
        files.append(dict(path=str(path),sha256=hashlib.sha256(raw).hexdigest()))
    return dict(provider='qwen_local',physical_attempts=attempts,usage_known_attempts=attempts-unknown,
        usage_unknown_attempts=unknown,known_prompt_tokens=prompt,known_completion_tokens=completion,
        known_total_tokens=prompt+completion,sum_physical_request_seconds=seconds,duration_unknown_attempts=duration_unknown,request_files=files,
        duplicate_physical_events_not_recharged=duplicates,money_cost=None,
        money_cost_reason='No measured local hardware, electricity, hosting or monetary tariff; local inference is not assumed free.',
        machine_energy_cost=None,unknown_usage_not_zero=True,
        elapsed_time_note='Sum of known individual HTTP durations; interrupted unknown durations excluded and counted separately; not batch wall-clock time.')
