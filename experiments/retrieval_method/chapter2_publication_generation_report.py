"""Read-only generation audit and review export; no gold or model calls."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import statistics

from chapter2_optimization_200 import RESOURCES, DATASET, read, sha
from chapter2_publication_200 import verify
from chapter2_common_qa_interface import neutral_messages
from chapter2_qa_deployment import prepared_messages, ANSWER_CHECKLIST


def replace_json(path,value):
    temp=path.with_suffix('.tmp')
    temp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    temp.replace(path)


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
        expected={**turn['request'],'messages':neutral_messages(prepared_messages(turn['request']['messages'],ANSWER_CHECKLIST))}
        if body!=expected:raise ValueError('Common model-facing prompt drift')
        fingerprint=hashlib.sha256(json.dumps(body,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        if fingerprint!=record['request_sha256']:raise ValueError('Request fingerprint drift')
        if record['provider']!='qwen_proxy' or record['model']!='qwen3-8b' or body['model']!='qwen3-8b':
            raise ValueError('Frozen deployment changed')
        if record['endpoint']!=read(root/'user-authorization.json')['endpoint']:raise ValueError('Authorized destination changed')
        if i==0 and body['messages'][1]['content']!=question:raise ValueError('Natural question changed')
        if body['max_tokens']>mb['output_tokens_per_request'] or turn['counted_input_tokens']>mb['input_tokens_per_request']:
            raise ValueError('Per-request model budget exceeded')
        if record['status']=='in_flight':raise ValueError('Closed answer has an unresolved request')
        statuses[record['status']]+=1
        raw=record.get('raw_response',{})
        if record['status']=='response' and raw.get('model')!='qwen3-8b':raise ValueError('Provider model mismatch')
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


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,required=True)
    p.add_argument('--final',action='store_true');a=p.parse_args();root=a.root.resolve()
    protocol=verify(root)
    if not a.final and (root/'generation-audit.json').exists():
        completed=read(root/'generation-audit.json')
        if completed['protocol_sha256']!=sha(root/'protocol.json') or not completed['generation_complete']:
            raise ValueError('Closed audit binding drift')
        replace_json(root/'generation-status.json',completed)
        print(json.dumps(completed,ensure_ascii=False))
        return
    questions={q['id']:q['question'] for q in read(root/'public-questions.json')}
    by_arm={};rows=[];cache={};bindings={};intervals=[];physical=Counter();usage=Counter();unknown_usage=0
    live=not a.final
    for arm in protocol['arms']:
        statuses=Counter();refs=Counter();tool_errors=0;request_count=0;tool_use=Counter();citation_delivery=Counter()
        paths=sorted((root/'generation'/arm).glob('*/result.json'))
        for path in paths:
            try:result=read(path)
            except json.JSONDecodeError:
                if live:continue
                raise
            qid=path.parent.name
            if qid not in questions or result['arm']!=arm or result['id']!=qid:raise ValueError('Unknown answer identity')
            statuses[result['status']]+=1
            refs[str(result.get('references_delivered'))]+=1
            if result['status']=='answered':
                citation_delivery['with_references_sessions']+=bool(result['references'])
                citation_delivery['without_references_sessions']+=not result['references']
                citation_delivery['nonempty_all_delivered_sessions']+=bool(result['references']) and result['references_delivered']
                citation_delivery['undelivered_or_malformed_reference_sessions']+=not result['references_delivered']
            tool_use['any_tool_sessions']+=bool(result['tool_events'])
            tool_use['original_evidence_sessions']+=bool(result['delivered_lines'])
            tool_use['search_sessions']+=any(e['name']=='search' for e in result['tool_events'])
            tool_use['direct_source_read_sessions']+=any(e['name']=='read_source' for e in result['tool_events'])
            tool_use['final_without_tools_sessions']+=result['status']=='answered' and not result['tool_events']
            tool_use['tool_calls']+=len(result['tool_events'])
            tool_use['delivered_characters']+=result['knowledge_characters']
            if a.final:
                audit=audit_session(root,arm,qid,questions[qid],protocol,cache)
                request_count+=audit['requests'];tool_errors+=audit['tool_errors']
                physical.update(audit['request_statuses']);usage.update(audit['known_usage']);unknown_usage+=audit['unknown_usage_requests']
                intervals.extend(audit['request_intervals']);bindings[arm+'/'+qid]=audit['result_sha256']
                rows.append(dict(arm=arm,id=qid,question=questions[qid],status=result['status'],
                    answer=result['answer'],references=result['references'],references_delivered=result.get('references_delivered'),
                    result_sha256=audit['result_sha256']))
        by_arm[arm]=dict(registered=200,closed=sum(statuses.values()),statuses=dict(statuses),
            reference_delivery_statuses=dict(refs),citation_delivery=dict(citation_delivery),tool_use=dict(tool_use),
            requests=request_count if a.final else None,tool_errors=tool_errors if a.final else None)
        if a.final:
            completion=read(root/'completion'/(arm+'.json'))
            if completion['sessions']!=200 or completion['statuses']!=dict(statuses):raise ValueError('Arm is not complete')
            if completion['protocol_sha256']!=sha(root/'protocol.json'):raise ValueError('Arm completion binding drift')
            if set(completion['results_sha256'])!=set(questions):raise ValueError('Missing or extra registered question')
            if any(completion['results_sha256'][qid]!=bindings[arm+'/'+qid] for qid in questions):raise ValueError('Frozen result binding drift')
    total=sum(v['closed'] for v in by_arm.values());answered=sum(v['statuses'].get('answered',0) for v in by_arm.values())
    summary=dict(schema='formal200_generation_status_v1',updated_utc=datetime.now(timezone.utc).isoformat(),
        registered=1400,closed=total,answered=answered,other_terminal_statuses=total-answered,
        by_arm=by_arm,protocol_sha256=sha(root/'protocol.json'),generation_complete=False,
        semantic_scores_available=False,external_export_authorized=True,
        boundary='Answered means a valid final JSON was delivered, not semantic correctness; all registered failures remain in the denominator.')
    if a.final:
        controller=read(root/'generation-controller-completion.json')
        if (total!=1400 or not controller['complete'] or set(controller['arms'])!=set(protocol['arms'])
                or controller['protocol_sha256']!=sha(root/'protocol.json')):
            raise ValueError('Generation grid incomplete')
        for rel,digest in protocol['implementation_sha256'].items():
            if sha(root/'runtime'/rel)!=digest:raise ValueError('Archived runtime snapshot drift')
        if sha(DATASET/'model/questions.json')!=protocol['questions_sha256'] or sha(DATASET/'binding.json')!=protocol['dataset_binding_sha256']:
            raise ValueError('Dataset identity drift')
        if sha(root/'provenance/adopted-chapter02.md')!=protocol['design_sha256']:
            raise ValueError('Adopted design snapshot drift')
        sweep=sorted([(start,1) for start,end in intervals]+[(end,-1) for start,end in intervals])
        active=maximum=0
        for _,delta in sweep:active+=delta;maximum=max(maximum,active)
        if maximum>14 or active!=0:raise ValueError('Registered physical request concurrency exceeded')
        summary.update(generation_complete=True,physical_requests=sum(physical.values()),request_statuses=dict(physical),
            known_usage=dict(usage),requests_with_unknown_usage=unknown_usage,max_observed_request_concurrency=maximum,
            result_bindings_sha256=hashlib.sha256(json.dumps(bindings,sort_keys=True).encode()).hexdigest(),
            audit_script_sha256=sha(Path(__file__)))
        with (root/'answers.jsonl').open('x',encoding='utf-8') as output:
            for row in rows:output.write(json.dumps(row,ensure_ascii=False)+'\n')
        summary['answers_jsonl_sha256']=sha(root/'answers.jsonl')
        with (root/'provenance/generation-report-source.py').open('xb') as output:output.write(Path(__file__).read_bytes())
        with (root/'generation-audit.json').open('x',encoding='utf-8') as output:
            json.dump(summary,output,ensure_ascii=False,indent=2)
    replace_json(root/'generation-status.json',summary)
    print(json.dumps(summary if a.final else {k:summary[k] for k in ['closed','answered','other_terminal_statuses','by_arm']},ensure_ascii=False))


if __name__=='__main__':main()
