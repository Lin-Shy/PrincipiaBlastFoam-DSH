"""Supplemental transport/cost cohorts; independent of answer quality and gold."""
import argparse
from collections import Counter,defaultdict
from datetime import datetime,timezone
import hashlib
from io import BytesIO
import json
from pathlib import Path
import statistics

from chapter2_sse_record_transport import collect,wire

def digest(data):return hashlib.sha256(data).hexdigest()

def verify_request(path,row):
    """Validate physical identity and replay successful streams from raw events."""
    if row.get('provider')!='qwen_proxy' or row.get('transport_attempts')!=1 or row.get('content_retries')!=0:
        raise ValueError('Expected recorded single-attempt proxy request')
    if row.get('model')!=row['request'].get('model') or digest(wire(row['request']))!=row['request_sha256']:
        raise ValueError('Wire identity or hash mismatch')
    policy=row.get('transport_policy','original_buffered_proxy')
    raw_hash=None
    if row['request'].get('stream'):
        logical=row['logical_request']
        if (logical.get('stream',False) or 'stream_options' in logical
            or digest(wire(logical))!=row['logical_request_sha256']
            or row['request']!={**logical,'stream':True,'stream_options':{'include_usage':True}}):
            raise ValueError('Unexpected logical-to-wire change')
        name=row['raw_sse_file']
        if Path(name).name!=name:raise ValueError('Raw SSE must be adjacent')
        raw=(path.parent/name).read_bytes();raw_hash=digest(raw)
        if raw_hash!=row['raw_response_sha256']:raise ValueError('Raw SSE changed')
        if row['status']=='response':
            payload=collect(BytesIO(raw),row['model'],BytesIO(),{},0)
            if (payload!=row['raw_response'] or payload!=row['response']
                    or digest(wire(payload))!=row['canonical_response_sha256']
                    or row.get('sse_done') is not True):raise ValueError('Canonical SSE response changed')
    elif 'logical_request' in row:
        raise ValueError('Unexpected logical request on a buffered receipt')
    return policy,raw_hash

def audit(root,allow_inflight=False):
    inventory={};groups=defaultdict(list);live=[]
    paths=sorted(path for path in root.rglob('*.json') if path.parent.name=='requests')
    for path in paths:
        data=path.read_bytes();row=json.loads(data)
        if row.get('status')=='in_flight':
            live.append(path.relative_to(root).as_posix())
            if not allow_inflight:raise ValueError('Unclosed physical request')
            continue
        policy,raw_hash=verify_request(path,row)
        revision=row.get('transport_revision_sha256')
        group=(row['model'],policy,revision)
        groups[group].append(row)
        inventory[path.relative_to(root).as_posix()]=dict(receipt_sha256=digest(data),raw_sse_sha256=raw_hash)
    cohorts=[]
    for (model,policy,revision),rows in sorted(groups.items(),key=lambda pair:str(pair[0])):
        durations=sorted(row['seconds'] for row in rows)
        known=[]
        for row in rows:
            payload=row.get('raw_response')
            usage=payload.get('usage') if isinstance(payload,dict) else None
            if not isinstance(usage,dict):usage={}
            if all(type(usage.get(k)) is int and usage[k]>=0 for k in ['prompt_tokens','completion_tokens']):known.append(usage)
        cohorts.append(dict(model=model,transport_policy=policy,transport_revision_sha256=revision,
            physical_attempts=len(rows),statuses=dict(Counter(row['status'] for row in rows)),
            started_utc_min=min(row['started_utc'] for row in rows),started_utc_max=max(row['started_utc'] for row in rows),
            latency_seconds_median=statistics.median(durations),latency_seconds_p95=durations[max(0,(95*len(durations)+99)//100-1)],
            sum_physical_seconds=sum(durations),usage_known_attempts=len(known),usage_unknown_attempts=len(rows)-len(known),
            known_prompt_tokens=sum(v['prompt_tokens'] for v in known),known_completion_tokens=sum(v['completion_tokens'] for v in known),
            money_cost=None))
    return dict(schema='quality_independent_transport_cohort_audit_v1',created_utc=datetime.now(timezone.utc).isoformat(),
        formal_result=False,quality_result=False,model_calls=0,root=str(root.resolve()),snapshot_only=allow_inflight,
        terminal_requests=len(inventory),in_flight_requests_excluded=live,cohorts=cohorts,inventory=inventory,
        limits=['Operational transport cohorts are post-start partitions, not randomized causal comparisons.',
            'A live snapshot is incomplete; no full-experiment completion or quality claim follows.',
            'Unknown usage remains unknown. No frozen monetary tariff or invoice is available.',
            'SSE successful canonical responses are independently replayed from raw bytes; legacy buffered receipts retain their original recorded hashes/objects.'])

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);parser.add_argument('--allow-inflight',action='store_true');args=parser.parse_args()
    if args.output.exists():raise FileExistsError('New immutable audit path required')
    value=audit(args.root,args.allow_inflight);args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x',encoding='utf-8') as f:json.dump(value,f,ensure_ascii=False,indent=2)
    print({k:value[k] for k in ['terminal_requests','snapshot_only','model_calls']})

if __name__=='__main__':main()
