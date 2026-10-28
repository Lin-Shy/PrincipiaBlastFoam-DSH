"""One synthetic native capability probe; never resend an uncertain POST."""
import argparse
from copy import deepcopy
import json
import re
import time
from urllib.parse import quote
import requests
import terra_candidate as c
import terra_native as native
from central_execution import Registry,exclusive_lock
from judge_api_adapter import digest

ROOT=c.core.DEFAULT_RUN/'evaluation/judges/terra_candidate/background'
PROTOCOL=c.core.DEFAULT_RUN/'release/protocol/terra_background_probe.json'


def request(item):
    profile,req,count=native.request(item,'medium')
    profile=deepcopy(profile);req=deepcopy(req)
    profile['stream']=False
    req['body'].update(stream=False,background=True,store=False,text={'format':{'type':'json_object'}})
    req.update(profile_sha256=digest(profile),request_sha256=digest(req['body']))
    assert count+profile['output_token_cap']<=32768
    return profile,req,count


def response_identity(raw,expected_id=None):
    if raw.get('model')!='gpt-6.1-terra':raise ValueError('model_identity_mismatch')
    rid=raw.get('id')
    if not isinstance(rid,str) or not re.fullmatch(r'resp_[A-Za-z0-9_-]+',rid):raise ValueError('invalid_response_id')
    if expected_id and rid!=expected_id:raise ValueError('response_id_changed')
    if raw.get('status') not in ('queued','in_progress','completed','failed','cancelled','incomplete'):raise ValueError('invalid_response_status')
    return rid


def probe(execute=False):
    p=c.core.read(PROTOCOL);assert p['manifest_sha256']==c.core.sha(c.core.DEFAULT_RUN/'release/manifests/test160_manifest.json')
    c.protocol()  # Hash-check the unchanged human references, Prompt and scoring rules.
    item=c.controls()[0];profile,req,count=request(item)
    if not execute:return dict(requests_sent=0,model=req['body']['model'],background=req['body'].get('background',False))
    c.stream.terra.rec.dc.guard_operational()
    ROOT.mkdir(parents=True,exist_ok=True)
    with exclusive_lock(ROOT/'probe.lock'):
        if (ROOT/'request.json').exists():
            # Even a prior receipt only permits a separately recorded GET reconciliation.
            return dict(state='existing_probe_hold_no_new_post',formal_replacement=False)
        c.stream.terra.s.save(ROOT/'request.json',dict(request=req,profile=profile,packet_item_sha256=digest(item),protocol_sha256=c.core.sha(PROTOCOL),input_token_estimate=count))
        key=Registry().private_key('gpt_sol');session=requests.Session();session.trust_env=False
        state=dict(status='unknown',started_utc=c.stream.terra.s.now(),post_maybe_sent=False,actual_cost='Unknown',formal_replacement=False)
        c.stream.terra.s.save(ROOT/'status.json',state)
        try:
            state['post_maybe_sent']=True
            response=session.post(req['url'],json=req['body'],headers={'Authorization':'Bearer '+key,'Accept':'application/json'},timeout=(15,60),allow_redirects=False)
            (ROOT/'receipt.txt').write_text(response.text.replace(key,'[REDACTED]'),encoding='utf-8')
            state.update(http_status=response.status_code,headers={k:v for k,v in response.headers.items() if k.lower() in ('x-request-id','content-type','retry-after')})
            if response.status_code!=200:
                state.update(status='explicit_http_rejection',reason='http_'+str(response.status_code));return state
            raw=response.json();rid=response_identity(raw);state['response_id']=rid
            c.stream.terra.s.save(ROOT/'status.json',state)
            for ordinal in range(p['max_get_polls']+1):
                response_identity(raw,rid)
                if raw['status']=='completed':
                    parsed=c.core.parse_current(profile,raw,item)
                    c.stream.terra.s.save(ROOT/'response.txt',raw);c.stream.terra.s.save(ROOT/'parsed.json',parsed)
                    record=parsed['record'];correct=all(x['score']==1 for x in record['points']) and record['fact_gate']==1 and record['applicability_gate']==1
                    state.update(status='valid_control' if correct else 'incorrect_control',usage=parsed['usage'],response_model=parsed['response_model'])
                    break
                if raw['status'] not in ('queued','in_progress'):
                    state.update(status='terminal_provider_failure',provider_status=raw['status']);break
                if ordinal==p['max_get_polls']:
                    state.update(status='pending_known_response_id');break
                time.sleep(p['poll_seconds'])
                response=session.get(req['url']+'/'+quote(rid,safe=''),headers={'Authorization':'Bearer '+key},timeout=(15,30),allow_redirects=False)
                (ROOT/('poll_'+str(ordinal+1)+'.txt')).write_text(response.text.replace(key,'[REDACTED]'),encoding='utf-8')
                if response.status_code!=200:
                    state.update(status='retrieval_hold',get_http_status=response.status_code);break
                raw=response.json()
        except Exception as exc:
            state.update(status='unknown_hold',error_type=type(exc).__name__,reason=str(exc).replace(key,'[REDACTED]')[:400])
        finally:
            session.close();state['completed_utc']=c.stream.terra.s.now();c.stream.terra.s.save(ROOT/'status.json',state)
        return state


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--execute',action='store_true');args=parser.parse_args()
    print(json.dumps(probe(args.execute)))
