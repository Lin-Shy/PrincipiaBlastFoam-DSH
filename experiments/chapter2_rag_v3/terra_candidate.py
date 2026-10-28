"""Bounded Terra streaming/reasoning development on calibration only, then locked audit."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import time
import terra_stream as stream
import terra_validation as original
import scoring as core
from central_execution import Registry,exclusive_lock
from judge_contract import VERSION,joint_metrics

ROOT=core.DEFAULT_RUN/'evaluation/judges/terra_candidate'
PROTOCOL=core.DEFAULT_RUN/'release/protocol/terra_candidate.json'
TRANSPORT_AMENDMENT=core.DEFAULT_RUN/'release/protocol/terra_candidate_transport_amendment.json'


def protocol():
    p=core.read(PROTOCOL)
    for name,expected in p['sources'].items():assert core.sha(core.DEFAULT_RUN/name)==expected
    for name in ['judge_prompt.txt','scoring_rules.json']:
        assert core.sha(Path(__file__).with_name(name))==core.read(core.DEFAULT_RUN/'evaluation/judges/protocol.json')['scoring_fingerprints'][name]
    return p


def controls():
    text='压力单位为Pa。writeControl=runTime时按仿真时间输出，不按时间步数输出。'
    base=dict(schema_version=VERSION,generation_failed=False,question='压力单位是什么？writeControl=runTime时按什么依据输出？',criteria=[dict(criterion_id='K001',claim='压力单位为Pa'),dict(criterion_id='K002',claim='runTime依据仿真时间而非时间步数')],conditional=True,sources=[dict(path='controls/reference.txt',file_sha256=hashlib.sha256(text.encode()).hexdigest(),text=text)])
    return [dict(base,sample_id='TC_correct',answer='压力单位为Pa；runTime依据仿真时间输出，不按时间步数。'),dict(base,sample_id='TC_wrong',answer='压力单位是m；runTime依据时间步数输出，与仿真时间无关。')]


def folders(root):return sorted(root.glob('attempt_*'),key=lambda x:int(x.name.split('_')[-1]))


def collect(phase,effort,items):
    found={}
    for item in items:
        for folder in folders(ROOT/phase/effort/item['sample_id']):
            if not (folder/'parsed.json').exists():continue
            parsed=stream.verify(folder,item,effort)
            found[item['sample_id']]=parsed['record'];break
    return found


def score(phase,effort,item,reg):
    root=ROOT/phase/effort/item['sample_id']
    existing=collect(phase,effort,[item])
    if existing:return 'reuse_valid'
    for folder in folders(root):
        state=core.read(folder/'status.json') if (folder/'status.json').exists() else {}
        rejected=stream.rejection((folder/'response.sse').read_text(encoding='utf-8')) if (folder/'response.sse').exists() else None
        if rejected:
            stream.terra.s.save(folder/'provider_rejection_resolution.json',dict(raw_sha256=core.sha(folder/'response.sse'),amendment_sha256=core.sha(TRANSPORT_AMENDMENT),**rejected))
        if not rejected and state.get('status')!='pre_send_failure' and state.get('http_status') not in (429,500,502,503,504):return 'existing_unknown_or_invalid_hold'
    amendment=core.read(TRANSPORT_AMENDMENT);assert amendment['base_protocol_sha256']==core.sha(PROTOCOL)
    for ordinal in range(len(folders(root))+1,amendment['max_attempts_per_item']+1):
        with stream.terra.slot('gpt_sol'):
            state=stream.attempt(root/('attempt_'+str(ordinal)),item,effort,reg,PROTOCOL,TRANSPORT_AMENDMENT)
        if state['status']=='valid':return 'valid'
        if state.get('reason') in ('model_identity_mismatch','usage_unknown_stop_and_reconcile') or state.get('http_status') in (400,401,403,404):return 'provider_or_identity_hold'
        if state['status'] not in ('pre_send_failure','provider_rejected') and state.get('http_status') not in (429,500,502,503,504):return 'unknown_or_invalid_hold'
        if ordinal<amendment['max_attempts_per_item']:time.sleep(amendment['backoff_seconds'][ordinal-1])
    return 'attempt_limit'


def calibration(effort,reg):
    packet=core.read(core.DEFAULT_RUN/'evaluation/judges/calibration.json')
    for item in controls():
        status=score('controls',effort,item,reg)
        print(json.dumps(dict(phase='controls',effort=effort,sample_id=item['sample_id'],status=status)),flush=True)
        if status=='provider_or_identity_hold':break
    labels=collect('controls',effort,controls())
    functional=len(labels)==2
    if functional:
        for item in controls():
            r=labels[item['sample_id']];expected=1 if item['sample_id']=='TC_correct' else 0
            functional= functional and all(x['score']==expected for x in r['points']) and r['fact_gate']==expected and r['applicability_gate']==expected
    if not functional:
        result=dict(effort=effort,status='functional_controls_incomplete' if len(labels)<2 else 'functional_controls_incorrect',functional=False,valid_controls=len(labels),expected_controls=2,complete=0)
        stream.terra.s.save(ROOT/(effort+'_calibration.json'),result);return result
    for item in packet['items']:
        status=score('calibration',effort,item,reg)
        print(json.dumps(dict(phase='calibration',effort=effort,sample_id=item['sample_id'],status=status)),flush=True)
        if status=='provider_or_identity_hold':break
    found=collect('calibration',effort,packet['items'])
    human={r['sample_id']:r for r in core.rows(core.DEFAULT_RUN/'evaluation/judges/human/scores.jsonl')}
    private={r['sample_id']:r for r in packet['private']}
    agreement=core.pair_statistics(human,found,packet['items'],private)
    complete=len(found)==18 and all(not joint_metrics(found[i['sample_id']],[k['criterion_id'] for k in i['criteria']],i['conditional'])['unknown_items'] for i in packet['items'] if i['sample_id'] in found)
    loss=None
    if complete:
        k=agreement['K']['exact'];ka=agreement['K']['quadratic_kappa']
        loss=max((1-k)/.1,.6/ka if ka and ka>0 else math.inf,*[agreement[n][field]/cap for n in ['EAS_arith','EAS_geo'] for field,cap in [('mae',5)]],*[abs(agreement[n]['bias_right_minus_left'])/3 for n in ['EAS_arith','EAS_geo']])
    if loss is not None and not math.isfinite(loss):loss=None
    result=dict(effort=effort,functional=True,complete=len(found),identified_complete=complete,calibration_only_agreement=agreement,selection_loss=loss)
    stream.terra.s.save(ROOT/(effort+'_calibration.json'),result);return result


def selected_report(effort):
    original.ROOT=ROOT/'selected';original.PROTOCOL=PROTOCOL
    original.ROOT.mkdir(exist_ok=True)
    original.collect=lambda phase,packet:collect(phase,effort,packet['items'])
    result=original.report()
    result.update(candidate_effort=effort,stream=True,candidate_selection=core.read(ROOT/'selection.json'))
    stream.terra.s.save(original.ROOT/'results.json',result)
    return result


def run(execute=False,controls_only=False):
    p=protocol();ROOT.mkdir(parents=True,exist_ok=True)
    if not (ROOT/'protocol.json').exists():stream.terra.s.save(ROOT/'protocol.json',p)
    assert core.read(ROOT/'protocol.json')==p
    stream.terra.s.save(ROOT/'transport_amendment.json',core.read(TRANSPORT_AMENDMENT))
    if not execute:return dict(requests_sent=0,candidates=p['candidates'])
    reg=Registry();stream.terra.rec.dc.guard_operational()
    with exclusive_lock(ROOT/'candidate.lock'):
        stream.terra.s.save(ROOT/'status.json',dict(state='controls' if controls_only else 'calibration_running',utc=stream.terra.s.now(),candidate_selection_uses_audit=False))
        if controls_only:
            def probe(effort):
                for item in controls():
                    status=score('controls',effort,item,reg)
                    print(json.dumps(dict(effort=effort,sample_id=item['sample_id'],status=status)),flush=True)
                    if status=='provider_or_identity_hold':break
            with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(probe,p['candidates']))
            stream.terra.s.save(ROOT/'status.json',dict(state='controls_finished',utc=stream.terra.s.now()));return
        if not (ROOT/'selection.json').exists():
            with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(lambda e:calibration(e,reg),p['candidates']))
            eligible=[r for r in results if r.get('identified_complete') and r.get('selection_loss') is not None]
            if not eligible:
                stream.terra.s.save(ROOT/'status.json',dict(state='calibration_incomplete_or_failed_controls',utc=stream.terra.s.now(),candidates=results,formal_replacement=False));return
            selected=min(eligible,key=lambda r:(r['selection_loss'],r['effort']!='medium'))
            stream.terra.s.save(ROOT/'selection.json',dict(effort=selected['effort'],utc=stream.terra.s.now(),calibration_only=True,audit_used_for_selection=False,selection_loss=selected['selection_loss'],candidate_summaries=results,protocol_sha256=core.sha(PROTOCOL)))
        selection=core.read(ROOT/'selection.json');assert selection['protocol_sha256']==core.sha(PROTOCOL)
        effort=selection['effort'];packet=core.read(core.DEFAULT_RUN/'evaluation/judges/audit/packet.json')
        stream.terra.s.save(ROOT/'status.json',dict(state='locked_audit_running',effort=effort,utc=stream.terra.s.now()))
        for item in packet['items']:
            status=score('audit',effort,item,reg)
            print(json.dumps(dict(phase='audit',effort=effort,sample_id=item['sample_id'],status=status)),flush=True)
            if status=='provider_or_identity_hold':break
        result=selected_report(effort)
        stream.terra.s.save(ROOT/'status.json',dict(state='finished',effort=effort,accepted=result['accepted'],decision=result['decision'],utc=stream.terra.s.now(),formal_replacement=False))
        print(json.dumps(dict(effort=effort,accepted=result['accepted'],decision=result['decision'])),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--execute',action='store_true');parser.add_argument('--controls-only',action='store_true');parser.add_argument('--native',action='store_true');args=parser.parse_args()
    if args.native:
        import terra_native
        terra_native.install();stream=terra_native
        ROOT=ROOT/'native';PROTOCOL=core.DEFAULT_RUN/'release/protocol/terra_native_candidate.json';TRANSPORT_AMENDMENT=core.DEFAULT_RUN/'release/protocol/terra_native_transport_amendment.json'
    print(json.dumps(run(args.execute,args.controls_only)))
