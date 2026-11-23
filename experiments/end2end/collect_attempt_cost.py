"""Read native DSH sessions into a provenance-linked ledger. No model/remote calls.

Session directories are explicit operator inputs; directory coverage is not proof
of complete provider billing. This does not change historical audit outputs.
"""
import argparse
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
from audit_development_sessions import read_events

FIELDS=('inputTokens','outputTokens','totalTokens','cacheReadTokens','cacheWriteTokens','reasoningTokens')
EVENTS={'assistant/message':'assistant_usage','compaction/summary':'compaction_usage',
        'llm/retry':'retry','tool/call':'tool_call','turn/end':'turn_end'}

def collect(roots):
    files={}
    for supplied in roots:
        root=Path(supplied).resolve()
        if not root.is_dir():raise FileNotFoundError(root)
        if os.name=='nt':root=Path('\\\\?\\'+str(root))
        for file in root.rglob('session.v2.jsonl.zstd'):
            files[str(file.resolve()).casefold() if os.name=='nt' else str(file.resolve())]=file
    ledger=[];sources=[];counts=Counter();totals=Counter();missing=Counter()
    for _,file in sorted(files.items()):
        sha=hashlib.sha256(file.read_bytes()).hexdigest()
        source_id=hashlib.sha256(str(file).encode()).hexdigest()[:16]
        events=read_events(file)
        sources.append({'path':str(file),'sha256':sha,'source_id':source_id,'events':len(events)})
        for line,event in enumerate(events,1):
            kind=event.get('type')
            if kind not in EVENTS:continue
            data=event.get('data') or {};counts[EVENTS[kind]]+=1
            row={'event_id':f'{source_id}:{line}','source_id':source_id,'source_sha256':sha,
                 'decoded_jsonl_line':line,'kind':EVENTS[kind],'native_type':kind,
                 'session_role':'unresolved','provider_request_id':None}
            if kind in ('assistant/message','compaction/summary'):
                usage=data.get('usage') or {};reported={}
                for key in FIELDS:
                    value=usage.get(key)
                    if value is None:missing[key]+=1;continue
                    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<0:
                        raise ValueError(f'Invalid usage at {source_id}:{line}:{key}')
                    reported[key]=value;totals[key]+=value
                row['reported_usage']=reported
                row['usage_status']='reported' if 'totalTokens' in reported else 'total_unknown'
            ledger.append(row)
    measured=counts['assistant_usage']+counts['compaction_usage']
    return {'schema':'chapter3_native_cost_v1','sources':sources,'events':ledger,
            'summary':{'sessions':len(sources),'event_counts':dict(counts),
                'reported_usage_sums':dict(totals),'usage_records':measured,'records_missing_field':dict(missing),
                'complete_provider_total_tokens':None,'actual_model_money':None,'actual_compute_money':None,
                'provider_request_count':None,'coverage':'no_sessions_found' if not sources else 'explicit_directories_only'},
            'limits':['Reported sums are partial if failed or unlogged requests lack usage.',
                      'Assistant messages are not asserted to be unique provider requests; no request IDs inferred.',
                      'Only top-level native usage counted; nested tool/context copies ignored; cache not added to total.',
                      'Main/subagent role is unresolved; all supplied sessions included.',
                      'Repeated source paths deduplicated; identical bytes in distinct sessions are retained.',
                      'No pricing, compute accounting, queue time or wall time invented.']}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--sessions-dir',action='append',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    result=collect(a.sessions_dir)
    with a.output.open('x',encoding='utf-8') as f:json.dump(result,f,ensure_ascii=False,indent=2)
    print(json.dumps(result['summary'],ensure_ascii=False))
