"""Source and request auditor derived from the completed experiment auditor.
Only model identity and the declared basic-tool message schema differ.
"""
from collections import Counter
from datetime import datetime
import hashlib
import json
from chapter2_optimization_200 import RESOURCES, read, sha
from chapter2_qa_deployment import prepared_messages

def audit_session(root,arm,qid,question,protocol,source_cache):
    folder=root/'generation'/arm/qid;result=read(folder/'result.json')
    protocol_sha=sha(root/'protocol.json')
    if result['id']!=qid or result['arm']!=arm or result['protocol_sha256']!=protocol_sha:
        raise ValueError('Answer identity/binding drift')
    budget=protocol['knowledge_budget'];mb=protocol['model_budget']
    if len(result['tool_events'])>budget['tool_calls'] or result['knowledge_characters']>budget['total_characters']:
        raise ValueError('Knowledge budget exceeded')
    if result['counted_input_tokens']>mb['input_tokens_total'] or result['actual_completion_tokens']>mb['output_tokens_total']:
        raise ValueError('Model budget exceeded')
    ledger=set();tool_errors=0
    source_hashes=read(RESOURCES/'source-map.json')['files']
    for event in result['tool_events']:
        response=event['response'];size=event['delivered_characters']
        if len(response)!=size or size>budget['tool_characters']:raise ValueError('Tool envelope budget drift')
        tool_errors+=event['status']=='tool_error'
        delivered=set()
        for block in (json.loads(response) if response else {}).get('evidence',[]):
            path=block['path']
            if path not in source_hashes:raise ValueError('Delivered source is outside the frozen corpus')
            if path not in source_cache:
                raw=(RESOURCES/'corpus'/path).read_bytes()
                source_cache[path]=(hashlib.sha256(raw).hexdigest(),raw.decode('utf-8').splitlines())
            digest,lines=source_cache[path]
            if block['sha256']!=digest or digest!=source_hashes[path]:raise ValueError('Delivered source hash mismatch')
            numbers=[line['number'] for line in block['lines']]
            if numbers!=list(range(block['start'],block['end']+1)):raise ValueError('Delivered source line range drift')
            for line in block['lines']:
                if lines[line['number']-1]!=line['text']:raise ValueError('Model did not receive original source text')
                delivered.add((path,line['number']))
        if delivered!={(r['path'],r['line']) for r in event['delivered_original_lines']}:
            raise ValueError('Per-tool source ledger drift')
        ledger|=delivered
    if ledger!={(r['path'],r['line']) for r in result['delivered_lines']}:
        raise ValueError('Final delivered source ledger drift')
    if sum(e['delivered_characters'] for e in result['tool_events'])!=result['knowledge_characters']:
        raise ValueError('Total tool envelope accounting drift')
    if arm=='none' and (ledger or result['tool_events']):raise ValueError('No-knowledge arm accessed sources')
    receipts=sorted((folder/'requests').glob('*.json'))
    if len(receipts)!=len(result['turns']):raise ValueError('Physical request/turn accounting drift')
    if len(receipts)>(1 if arm=='none' else budget['tool_calls']+1):raise ValueError('Turn limit exceeded')
    statuses=Counter();usage=Counter();unknown_usage=0;seconds=[];intervals=[]
    for i,(path,turn) in enumerate(zip(receipts,result['turns'])):
        record=read(path);body=record['request']
        if path.stem!=f'{i:02d}' or record['transport_attempts']!=1 or record['content_retries']!=0:
            raise ValueError('A request was replayed or repaired')
        expected={**turn['request'],'messages':prepared_messages(turn['request']['messages'],protocol['common_answer_checklist'])}
        if body!=expected:raise ValueError('Common model-facing prompt drift')
        fingerprint=hashlib.sha256(json.dumps(body,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        if fingerprint!=record['request_sha256']:raise ValueError('Request fingerprint drift')
        if record['provider']!='qwen_proxy' or record['model']!=protocol['answer_model'] or body['model']!=protocol['answer_model']:
            raise ValueError('Frozen deployment changed')
        if record['endpoint']!=read(root/'user-authorization.json')['endpoint']:raise ValueError('Authorized destination changed')
        if i==0 and body['messages'][1]['content']!=question:raise ValueError('Natural question changed')
        if body['max_tokens']>mb['output_tokens_per_request'] or turn['counted_input_tokens']>mb['input_tokens_per_request']:
            raise ValueError('Per-request model budget exceeded')
        if record['status']=='in_flight':raise ValueError('Closed answer has an unresolved request')
        statuses[record['status']]+=1
        raw=record.get('raw_response',{})
        if record['status']=='response' and raw.get('model')!=protocol['answer_model']:raise ValueError('Provider model mismatch')
        u=raw.get('usage')
        if isinstance(u,dict) and all(type(u.get(k)) is int for k in ['prompt_tokens','completion_tokens','total_tokens']):
            for key in ['prompt_tokens','completion_tokens','total_tokens']:usage[key]+=u[key]
        else:unknown_usage+=1
        seconds.append(record['seconds'])
        start=datetime.fromisoformat(record['started_utc']).timestamp()
        intervals.append((start,start+record['seconds']))
    valid_refs=None
    if result['status']=='answered':
        valid_refs=True
        for ref in result['references']:
            if (not isinstance(ref,dict) or set(ref)!={'path','start','end'} or type(ref.get('start')) is not int
                    or type(ref.get('end')) is not int or not 1<=ref['start']<=ref['end']):
                valid_refs=False;break
            if any((ref['path'],n) not in ledger for n in range(ref['start'],ref['end']+1)):
                valid_refs=False;break
        if valid_refs!=result['references_delivered']:raise ValueError('Reference delivery validation drift')
    return dict(status=result['status'],references_delivered=valid_refs,tool_errors=tool_errors,
        requests=len(receipts),request_statuses=dict(statuses),known_usage=dict(usage),unknown_usage_requests=unknown_usage,
        request_seconds=seconds,request_intervals=intervals,result_sha256=sha(folder/'result.json'))

