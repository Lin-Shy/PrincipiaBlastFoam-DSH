"""Fixed human-reference Terra validation; no Test160-driven model selection."""
import argparse
import json
import time
from pathlib import Path
import scoring as core
from judge_contract import joint_metrics
from judge_statistics import metric_error
import test160_terra as terra
from central_execution import Registry, exclusive_lock

ROOT=core.DEFAULT_RUN/'evaluation/judges/terra_validation'
PROTOCOL=core.DEFAULT_RUN/'release/protocol/terra_validation.json'


def read_lines(p):return core.rows(p)


def inputs():
    protocol=core.read(PROTOCOL)
    for name,expected in protocol['sources'].items():
        assert core.sha(core.DEFAULT_RUN/name)==expected, 'Validation reference changed: '+name
    source=core.DEFAULT_RUN/'evaluation/judges'
    result={}
    for phase,base,packetfile in [('audit',source/'audit','packet.json'),('calibration',source,'calibration.json')]:
        packet=core.read(base/packetfile)
        assert len(packet['items'])==(12 if phase=='audit' else 18)
        labels={j:{r['sample_id']:r for r in read_lines(base/('human/scores.jsonl' if j=='human' else 'results/'+j+'.jsonl'))} for j in ['human','gpt_sol','deepseek_flash']}
        assert all(len(labels[j])==len(packet['items']) for j in labels)
        result[phase]=(packet,labels)
    return protocol,result


def collect(phase,packet):
    labels={}
    for item in packet['items']:
        root=ROOT/phase/'requests'/item['sample_id']
        valid=[]
        for folder in terra.rec.folders(root):
            saved=core.read(folder/'request.json');terra.check_request(saved,item)
            if not (folder/'response.txt').exists():continue
            try:parsed=core.parse_current(saved['profile'],core.read(folder/'response.txt'),item)
            except (ValueError,KeyError,TypeError):continue
            valid.append(parsed)
        if valid:labels[item['sample_id']]=valid[0]['record']
    return labels


def report():
    protocol,data=inputs();out={};fail=[];missing=[];red=[]
    for phase,(packet,old) in data.items():
        items=packet['items'];private={p['sample_id']:p for p in packet['private']}
        current=collect(phase,packet)
        agreement=core.pair_statistics(old['human'],current,items,private)
        dual={n:[] for n in core.METRICS}
        for item in items:
            sid=item['sample_id'];r=current.get(sid)
            if not r:missing.append(phase+':'+sid);continue
            ks=[x['criterion_id'] for x in item['criteria']]
            tm=joint_metrics(r,ks,item['conditional']);dm=joint_metrics(old['deepseek_flash'][sid],ks,item['conditional']);hm=joint_metrics(old['human'][sid],ks,item['conditional'])
            if tm['unknown_items'] or tm['missing_items']:missing.append(phase+':'+sid+':unknown')
            for n in core.METRICS:
                k='EAS_'+n
                if all(m[k] is not None for m in [tm,dm,hm]):dual[n].append((private[sid]['question_id'],(tm[k]+dm[k])/2-hm[k]))
            h=old['human'][sid]
            if type(h['fact_gate']) in (float,int) and type(r['fact_gate']) in (float,int) and h['fact_gate']<=.25 and r['fact_gate']>=.75:
                red.append(dict(phase=phase,sample_id=sid,kind='potential_severe_fact_false_pass'))
            if item['conditional'] and type(h['applicability_gate']) in (float,int) and type(r['applicability_gate']) in (float,int) and abs(h['applicability_gate']-r['applicability_gate'])>=.5:
                red.append(dict(phase=phase,sample_id=sid,kind='potential_substantive_condition_error'))
        out[phase]=dict(expected=len(items),complete=len(current),terra_vs_human=agreement,
            sol_vs_human=core.pair_statistics(old['human'],old['gpt_sol'],items,private),
            terra_vs_sol=core.pair_statistics(old['gpt_sol'],current,items,private),
            terra_deepseek_mean_vs_human={'EAS_'+n:metric_error(ds) for n,ds in dual.items()})
    a=out['audit']['terra_vs_human'];g=protocol['thresholds']
    if a['K']['exact'] is None or a['K']['exact']<g['K_exact_min']:fail.append('K_exact')
    if a['K']['quadratic_kappa'] is None or a['K']['quadratic_kappa']<g['K_quadratic_kappa_min']:fail.append('K_kappa')
    for n in ['EAS_arith','EAS_geo']:
        if a[n]['mae'] is None or a[n]['mae']>g[n+'_MAE_max']:fail.append(n+':MAE')
        if a[n]['bias_right_minus_left'] is None or abs(a[n]['bias_right_minus_left'])>g[n+'_abs_bias_max']:fail.append(n+':Bias')
    audit_flags=[r for r in red if r['phase']=='audit']
    accepted=not missing and not fail and not audit_flags
    decision='pending_missing_or_unknown' if missing else 'fail' if fail else 'manual_review' if audit_flags else 'pass_fixed_historical_reference_only'
    result=dict(created_utc=terra.s.now(),model='gpt-6.1-terra',accepted=accepted,decision=decision,failed_gates=fail,missing_or_unknown=missing,professional_red_flags=red,phases=out,protocol_sha256=core.sha(PROTOCOL),original_audit_modified=False,unseen_independent_audit=False,full_sol_replacement_permitted=accepted,full_sol_replacement_completed=False)
    terra.s.save(ROOT/'results.json',result)
    return result


def run():
    protocol,data=inputs();ROOT.mkdir(parents=True,exist_ok=True)
    if not (ROOT/'protocol.json').exists():terra.s.save(ROOT/'protocol.json',protocol)
    assert core.read(ROOT/'protocol.json')==protocol
    reg=Registry();terra.rec.dc.guard_operational();terra.rec.request=terra.request;terra.s.OUT=ROOT
    count=0;states={};halt=False
    with exclusive_lock(ROOT/'validation.lock'):
        for phase,(packet,_) in data.items():
            for item in packet['items']:
                sid=item['sample_id'];root=ROOT/phase/'requests'/sid
                if sid in collect(phase,packet):state='reuse_valid'
                else:
                    state='attempt_limit'
                    for ordinal in range(1,4):
                        folder=root/'recovery'/('attempt_'+str(ordinal))
                        if folder.exists():
                            if not (folder/'response.txt').exists():state='transport_unknown_no_resend';break
                            st=core.read(folder/'status.json') if (folder/'status.json').exists() else {}
                            if st.get('http_status') not in terra.rec.RETRY_HTTP:state='existing_invalid_hold';break
                            continue
                        with terra.slot('gpt_sol'):
                            st=terra.rec.attempt(root,'gpt_sol',item,ordinal,reg)
                        count+=1;state=st['status']
                        if state=='valid':break
                        if state=='unknown':state='transport_unknown_no_resend';break
                        if st.get('reason') in ('model_identity_mismatch','usage_unknown_stop_and_reconcile','http_403','http_404'):
                            halt=True;break
                        if st.get('http_status') not in terra.rec.RETRY_HTTP:break
                        time.sleep(5 if ordinal<2 else 20)
                states[phase+':'+sid]=state
                result=report()
                terra.s.save(ROOT/'status.json',dict(utc=terra.s.now(),state='held' if halt else 'running',requests_sent=count,processed=len(states),expected=30,states=states))
                print(json.dumps(dict(phase=phase,sample_id=sid,status=state,requests=count)),flush=True)
                if halt:break
            if halt:break
    result=report()
    terra.s.save(ROOT/'status.json',dict(utc=terra.s.now(),state='held' if halt else 'finished',requests_sent=count,processed=len(states),expected=30,states=states,accepted=result['accepted']))
    print(json.dumps(dict(decision=result['decision'],accepted=result['accepted'],failed_gates=result['failed_gates'],missing=len(result['missing_or_unknown']))),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--execute',action='store_true');a=p.parse_args()
    if a.execute:run()
    else:print(json.dumps(report(),ensure_ascii=False))
