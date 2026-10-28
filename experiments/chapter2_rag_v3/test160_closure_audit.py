"""Read-only raw-response audit; no network, no regeneration, no score selection."""
from collections import Counter
from pathlib import Path
import csv
import hashlib
import json
import scoring
import single_pass_dev40 as s
from judge_api_adapter import digest

BASE = s.RUN / 'test160_runs'
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p): return json.loads(p.read_text(encoding='utf-8-sig'))

def run():
    started=s.now()
    rows=[]; errors=[]; bindings={}; summary={}
    manifest=s.RUN/'release/manifests/test160_manifest.json'; mh=sha(manifest)
    for mode,base,n in [('agentic',BASE,4160),('single_pass',BASE/'supplement/single_pass',960)]:
        packet=read(base/'scoring/packet.json'); assert len(packet['items'])==n
        identities=set(); samples=set()
        for row in packet['items']:
            item=row['item']; sid=item['sample_id']; identity=(row['model'],row['method'],row['qid'])
            assert identity not in identities and sid not in samples
            identities.add(identity); samples.add(sid)
            fp=s.RUN/row['generation_file']; raw=read(fp)
            assert sha(fp)==row['generation_sha256'] and raw['manifest_sha256']==mh
            assert sid=='T'+hashlib.sha256((fp.parent.parent.name+'|'+row['qid']+'|'+sha(fp)).encode()).hexdigest()[:20]
            assert item['answer']==(raw.get('answer') or '')
            assert item['generation_failed']==(raw['status']!='answered')
            bindings[str(fp.relative_to(s.RUN))]=sha(fp)
            result=dict(mode=mode,model=row['model'],method=row['method'],question_id=row['qid'],sample_id=sid,generation_status=raw['status'],generation_sha256=sha(fp))
            for judge in s.JUDGES:
                root=base/'scoring'/judge/sid
                valid=[]; reasons=[]; attempts=[]
                folders=([root] if (root/'request.json').exists() else [])+sorted((root/'recovery').glob('attempt_*'),key=lambda p:int(p.name.split('_')[-1]))
                for folder in folders:
                    req=read(folder/'request.json'); state=read(folder/'status.json') if (folder/'status.json').exists() else {}
                    if req['request']['body']['model']=='gpt-6.1-terra':
                        import test160_terra
                        test160_terra.amendment()
                        test160_terra.check_request(req,item)
                    if 'request_sha256' in req:assert req['request_sha256']==digest(req['request']['body'])
                    if 'packet_item_sha256' in req:assert req['packet_item_sha256']==digest(item)
                    attempts.append(dict(path=str(folder.relative_to(s.RUN)),status=state.get('status'),reason=state.get('reason'),http_status=state.get('http_status')))
                    response=folder/'response.txt'
                    for p in [folder/'request.json',response,folder/'status.json']:
                        if p.exists():bindings[str(p.relative_to(s.RUN))]=sha(p)
                    if response.exists():
                        try:
                            parsed=scoring.parse_current(req['profile'],read(response),item)
                            valid.append((folder,parsed))
                        except (ValueError,KeyError,TypeError,json.JSONDecodeError) as exc: reasons.append(str(exc))
                if item['generation_failed']: status='generation_failure_zero'
                elif valid:
                    assert (root/'parsed.json').exists(), 'Recoverable saved response needs reconciliation: '+str(root)
                    canonical=read(root/'parsed.json')
                    assert any(p['record']==canonical['record'] for _,p in valid)
                    assert any(p['raw_response_sha256']==canonical['raw_response_sha256'] and p['response_model']==canonical['response_model'] for _,p in valid)
                    bindings[str((root/'parsed.json').relative_to(s.RUN))]=sha(root/'parsed.json')
                    status='valid'
                elif (root/'input_hold.json').exists():status='input_budget_hold'
                elif any(a['reason']=='Scoring identity mismatch' for a in attempts):status='scoring_identity_hold'
                elif any(a['reason']=='model_identity_mismatch' for a in attempts):status='model_identity_hold'
                elif any(a['http_status'] is None for a in attempts):status='transport_unknown_no_resend'
                elif attempts and attempts[-1]['http_status']==403:status='provider_billing_403'
                elif attempts and attempts[-1]['http_status']==404:status='model_unavailable_404'
                elif any(a['reason']=='usage_unknown_stop_and_reconcile' for a in attempts):status='provider_error_without_identity_usage'
                elif attempts and attempts[-1]['http_status'] in (429,500,502,503,504):status='recoverable_http_within_attempt_limit'
                elif attempts:status='invalid_response_hold'
                elif (BASE/('STOP_'+judge+'.json')).exists():status='branch_stopped_not_sent'
                else:status='missing_not_sent'
                result[judge]=status; result[judge+'_response_model']=canonical['response_model'] if status=='valid' else None
                result[judge+'_attempts']=json.dumps(attempts,ensure_ascii=False); result[judge+'_parse_errors']=json.dumps(reasons,ensure_ascii=False)
            count=sum(result[j]=='valid' for j in s.JUDGES)
            result['answer_class']='formal_generation_failure' if item['generation_failed'] else ['no_valid_judge','one_valid_judge','dual_valid'][count]
            rows.append(result)
        assert len(identities)==n
        cells=Counter((r['model'],r['method']) for r in rows if r['mode']==mode);assert all(v==160 for v in cells.values())
        summary[mode]=dict(tasks=n,answers=dict(Counter(r['answer_class'] for r in rows if r['mode']==mode)),judges={j:dict(Counter(r[j] for r in rows if r['mode']==mode)) for j in s.JUDGES})
    out=s.RUN/'results/tables/closure_audit.csv'
    with out.open('w',encoding='utf-8-sig',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    valid=sum(r['answer_class']=='dual_valid' for r in rows); answered=sum(r['answer_class']!='formal_generation_failure' for r in rows)
    report=dict(schema='test160_raw_closure_audit',manifest_sha256=mh,generation_tasks=len(rows),answered=answered,formal_failures=len(rows)-answered,dual_valid=valid,dual_completion_rate=valid/answered,missing_dual=answered-valid,formal_experiment_complete=valid==answered,modes=summary,requests_sent=0,source_hashes=bindings,irrecoverable_missing_tasks='Not established: provider/account and unresolved transport states require external reconciliation',protocol_unchanged=True)
    report['judge_model_counts']={j:dict(Counter(r[j+'_response_model'] for r in rows if r[j]=='valid')) for j in s.JUDGES}
    amended=(s.RUN/'release/protocol/test160_gpt_terra_amendment.json').exists()
    report.update(protocol_unchanged=not amended,scoring_rules_and_generation_unchanged=True,judge_model_amended=amended,original_frozen_dual_model_experiment=not amended)
    report['audit_interval_utc']=[started,s.now()]
    report['live_progress_check_not_manuscript_statistical_snapshot']=True
    s.save(BASE/'closure_audit.json',report)
    print(json.dumps({k:v for k,v in report.items() if k!='source_hashes'},ensure_ascii=False))
if __name__=='__main__':run()
