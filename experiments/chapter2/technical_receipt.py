"""Verify saved live traffic offline. Transport checks and answer accuracy differ."""
from pathlib import Path
import json,collections
from models import EXPERIMENT,MODELS,encoded,sha,now,strict_json
from tokenization import ChatCounter
from runtime import action_content,parse_action,wire

def main():
    root=EXPERIMENT/'technical/structured_final_20261103';models={};files={};calls=0
    for model in MODELS:
        folder=root/model;cases=[];counter=ChatCounter(model)
        summary=json.loads((folder/'summary.json').read_text('utf-8'))
        assert summary['tokenizer']==counter.public()
        for path in sorted(folder.glob('*/result.json')):
            r=json.loads(path.read_text('utf-8'));requests=sorted((path.parent/'requests').glob('*.json'));calls+=len(requests)
            ok=r['status']=='answered' and len(requests)==len(r['turns'])
            if r['mode']=='agentic':ok=ok and len(requests)>=3 and len(r['tool_events'])>=2
            for req,t in zip(requests,r['turns']):
                v=json.loads(req.read_text('utf-8'));raw=v.get('raw_response',{});u=raw.get('usage',{})
                ok=ok and v['status']=='response' and raw.get('model')==summary['deployment']['api_model'] and sha(encoded(v['request']))==v['request_sha256']==t['request_sha256']
                ok=ok and counter(v['request']['messages'])==u.get('prompt_tokens') and u['prompt_tokens']+v['request']['max_tokens']<=32768 and u.get('completion_tokens',999999)<=2048
                ok=ok and raw['choices'][0]['finish_reason']=='stop'
                obj=strict_json(action_content(raw['choices'][0]['message']['content']))
                if r['checks']['part']=='objective' and obj['action']=='final':
                    ok=ok and isinstance(obj.get('final_answer'),str) and bool(obj['final_answer'].strip())
                    obj={k:v for k,v in obj.items() if k!='final_answer'}
                allowed={'glob','grep','read_source'} if r['method']=='basic' else {'catalog','search','read_source'}
                parse_action(wire(obj),allowed,t['final_only'])
            cases.append(dict(case=path.parent.name,interface_passed=ok,answer_probe_correct=r['checks']['answer_check']))
        token=[]
        for path in sorted(folder.glob('tokenize_*.json')):
            row=json.loads(path.read_text('utf-8'));ids=counter.ids(row['request']['messages'])
            token.append(ids==row['response']['tokens'] and len(ids)==row['response']['count'])
        models[model]=dict(interface_passed=len(cases)==7 and all(x['interface_passed'] for x in cases) and all(token),
            cases=cases,exact_token_id_fixtures=len(token),answer_probes_correct=sum(x['answer_probe_correct'] for x in cases),answer_probes_total=len(cases))
    for p in root.rglob('*.json'):files[p.relative_to(EXPERIMENT).as_posix()]=sha(p.read_bytes())
    traffic=collections.Counter();statuses=collections.Counter()
    for p in (EXPERIMENT/'technical').glob('*/*/*/requests/*.json'):
        v=json.loads(p.read_text('utf-8'));traffic[v['deployment']['logical_model']]+=1;statuses[v['status']]+=1
    report=dict(schema='current_interface_acceptance_v1',verified_utc=now(),live_run=root.name,passed=all(v['interface_passed'] for v in models.values()),
        models=models,final_run_chat_requests=calls,all_preparation_chat_submission_attempts=sum(traffic.values()),all_preparation_request_statuses=dict(statuses),
        formal_questions_used=0,gold_used=False,formal_generation_started=False,
        interpretation='Interface pass requires actual model identity, valid JSON actions, 2 tool rounds where requested, exact chat token counts, per-request limits and normal stop. Arithmetic probe accuracy is reported separately; it is not an interface gate or a formal QA score.',
        prior_reports='All original runs and their initial combined pass/fail flags are preserved. This receipt separates content mistakes from transport/schema faults; no failed answer is repaired or retried.',files=files)
    (EXPERIMENT/'release/validation/interface_checks.json').write_bytes(encoded(report))
    print(json.dumps({k:v for k,v in report.items() if k not in {'files','models'}}))

if __name__=='__main__':main()
