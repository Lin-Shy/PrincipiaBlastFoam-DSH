"""Fixed human-reference Terra validation; no Test160-driven model selection."""
import argparse
import json
import csv
import time
from html import escape
from pathlib import Path
import scoring as core
from judge_contract import joint_metrics, calculate
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
    protocol,data=inputs();out={};fail=[];missing=[];red=[];paired_rows=[]
    for phase,(packet,old) in data.items():
        items=packet['items'];private={p['sample_id']:p for p in packet['private']}
        current=collect(phase,packet)
        agreement=core.pair_statistics(old['human'],current,items,private)
        dual={n:[] for n in core.METRICS}
        error_bounds={n:[] for n in core.METRICS};bias_bounds={n:[] for n in core.METRICS}
        total_points=matches=mismatches=0
        for item in items:
            sid=item['sample_id'];r=current.get(sid)
            ks=[x['criterion_id'] for x in item['criteria']]
            h=old['human'][sid];hm=joint_metrics(h,ks,item['conditional'])
            tm=joint_metrics(r,ks,item['conditional']) if r else calculate([None]*len(ks),None,None if item['conditional'] else 'not_applicable',item['conditional'])
            row=dict(phase=phase,sample_id=sid,question_id=private[sid]['question_id'],terra_response_valid=r is not None)
            for label,record in [('human',h),('sol',old['gpt_sol'][sid]),('deepseek',old['deepseek_flash'][sid]),('terra',r)]:
                m=joint_metrics(record,ks,item['conditional']) if record else tm
                for name in ['K','F','A','EAS_arith','EAS_geo','eas_arith_bounds','eas_geo_bounds']:
                    row[label+'_'+name]=m[name]
            paired_rows.append(row)
            total_points+=len(ks)
            hp={x['criterion_id']:x['score'] for x in h['points']}
            for point in r['points'] if r else []:
                if type(point['score']) in (int,float):
                    matches+=int(point['score']==hp[point['criterion_id']]);mismatches+=int(point['score']!=hp[point['criterion_id']])
            for n in core.METRICS:
                lo,hi=tm['eas_'+n+'_bounds'];human=hm['EAS_'+n]
                error_bounds[n].append([0. if lo<=human<=hi else min(abs(lo-human),abs(hi-human)),max(abs(lo-human),abs(hi-human))])
                bias_bounds[n].append([lo-human,hi-human])
            if not r:missing.append(phase+':'+sid);continue
            dm=joint_metrics(old['deepseek_flash'][sid],ks,item['conditional'])
            if tm['unknown_items'] or tm['missing_items']:missing.append(phase+':'+sid+':unknown')
            for n in core.METRICS:
                k='EAS_'+n
                if all(m[k] is not None for m in [tm,dm,hm]):dual[n].append((private[sid]['question_id'],(tm[k]+dm[k])/2-hm[k]))
            if type(h['fact_gate']) in (float,int) and type(r['fact_gate']) in (float,int) and h['fact_gate']<=.25 and r['fact_gate']>=.75:
                red.append(dict(phase=phase,sample_id=sid,kind='potential_severe_fact_false_pass'))
            if item['conditional'] and type(h['applicability_gate']) in (float,int) and type(r['applicability_gate']) in (float,int) and abs(h['applicability_gate']-r['applicability_gate'])>=.5:
                red.append(dict(phase=phase,sample_id=sid,kind='potential_substantive_condition_error'))
        out[phase]=dict(expected=len(items),complete=len(current),terra_vs_human=agreement,
            sol_vs_human=core.pair_statistics(old['human'],old['gpt_sol'],items,private),
            sol_vs_human_on_terra_valid_answers=core.pair_statistics(old['human'],old['gpt_sol'],[i for i in items if i['sample_id'] in current],private),
            terra_vs_sol=core.pair_statistics(old['gpt_sol'],current,items,private),
            terra_deepseek_mean_vs_human={'EAS_'+n:metric_error(ds) for n,ds in dual.items()},
            full_denominator_bounds=dict(K_exact=[matches/total_points,1-mismatches/total_points],necessary_points=total_points,
                **{'EAS_'+n:dict(MAE=[sum(b[j] for b in error_bounds[n])/len(items) for j in (0,1)],Bias=[sum(b[j] for b in bias_bounds[n])/len(items) for j in (0,1)]) for n in core.METRICS}),bounds_interpretation='Missing-grade identification bounds, not confidence intervals')
    a=out['audit']['terra_vs_human'];g=protocol['thresholds']
    if a['K']['exact'] is None or a['K']['exact']<g['K_exact_min']:fail.append('K_exact')
    if a['K']['quadratic_kappa'] is None or a['K']['quadratic_kappa']<g['K_quadratic_kappa_min']:fail.append('K_kappa')
    for n in ['EAS_arith','EAS_geo']:
        if a[n]['mae'] is None or a[n]['mae']>g[n+'_MAE_max']:fail.append(n+':MAE')
        if a[n]['bias_right_minus_left'] is None or abs(a[n]['bias_right_minus_left'])>g[n+'_abs_bias_max']:fail.append(n+':Bias')
    audit_flags=[r for r in red if r['phase']=='audit']
    accepted=not missing and not fail and not audit_flags
    decision='pending_missing_or_unknown' if missing else 'fail' if fail else 'manual_review' if audit_flags else 'pass_fixed_historical_reference_only'
    identified=a['paired_answers']==12 and all(a[n]['identified_pairs']==12 for n in ['EAS_arith','EAS_geo']) and a['K']['unknown_pairs']==0
    result=dict(created_utc=terra.s.now(),model='gpt-6.1-terra',accepted=accepted,decision=decision,failed_gates=fail if identified else [],observed_subset_gate_flags=fail if not identified else [],missing_or_unknown=missing,professional_red_flags=red,phases=out,protocol_sha256=core.sha(PROTOCOL),original_audit_modified=False,unseen_independent_audit=False,full_sol_replacement_permitted=accepted,full_sol_replacement_completed=False)
    terra.s.save(ROOT/'results.json',result)
    with (ROOT/'per_answer.csv').open('w',encoding='utf-8-sig',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(paired_rows[0]));writer.writeheader()
        writer.writerows({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v for k,v in row.items()} for row in paired_rows)
    def fmt(x):return '未识别' if x is None else f'{x:.4f}'
    h=['<html lang="zh-CN"><meta charset="utf-8"><title>Terra固定人工参考验证</title><body style="font:16px/1.7 system-ui;max-width:1100px;margin:30px auto"><h1>Terra固定人工参考验证</h1>',
       '<p>判定：'+escape(decision)+'；自动通过：'+str(accepted)+'。已有历史样本复用，不称新独立未见审计。缺评或Unknown阻止通过，不补零或择优重试。</p>',
       '<table border="1" cellpadding="7" style="border-collapse:collapse"><tr><th>样本</th><th>裁判</th><th>已评分/固定回答数</th><th>K一致率界限（0–1）</th><th>完整样本Kappa</th><th>算术MAE/Bias界限</th><th>几何MAE/Bias界限</th></tr>']
    def interval(b):return '['+fmt(b[0])+', '+fmt(b[1])+']'
    for phase,v in out.items():
        for name,key in [('Terra','terra_vs_human'),('Sol（原记录）','sol_vs_human')]:
            z=v[key]
            b=v['full_denominator_bounds'] if key=='terra_vs_human' else dict(K_exact=[z['K']['exact']]*2,**{n:dict(MAE=[z[n]['mae']]*2,Bias=[z[n]['bias_right_minus_left']]*2) for n in ['EAS_arith','EAS_geo']})
            complete=z['paired_answers']==v['expected'] and z['K']['unknown_pairs']==0
            h.append('<tr>'+''.join('<td>'+escape(str(x))+'</td>' for x in [phase,name,str(z['paired_answers'])+'/'+str(v['expected']),interval(b['K_exact']),fmt(z['K']['quadratic_kappa']) if complete else '待完整评分',interval(b['EAS_arith']['MAE'])+'/'+interval(b['EAS_arith']['Bias']),interval(b['EAS_geo']['MAE'])+'/'+interval(b['EAS_geo']['Bias'])])+'</tr>')
    h.append('</table><p>全部区间使用固定完整分母，属于缺评识别界限，不是95%置信区间；完整结果上下界相等。部分评分的配对误差另保留在JSON中，不能代替全样本验收。原DeepSeek审计未通过的事实不因Terra验证改变。</p><p><a href="results.json">逐项统计与门槛</a> · <a href="../../../release/protocol/terra_validation.json">验证协议</a></p></body></html>')
    (ROOT/'index.html').write_text('\n'.join(h),encoding='utf-8')
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
