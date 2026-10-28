"""Validate native JSON/no-reasoning Terra against fixed human references."""
import argparse
import json
import sys
import time
import requests
import terra_candidate as c
import terra_foreground_probe as probe
from judge_api_adapter import digest

terra=c.stream.terra
BASE_COLLECT=c.collect
PROBE_ROOT=c.core.DEFAULT_RUN/'evaluation/judges/terra_candidate/foreground'


def request(item,effort):
    if effort!='none':raise ValueError('Unapproved foreground effort')
    return probe.request(item)


def verify(folder,item,effort):
    profile,req,_=request(item,effort);saved=c.core.read(folder/'request.json')
    assert saved['request']==req and saved['profile']==profile
    actual=c.core.parse_current(profile,c.core.read(folder/'response.txt'),item)
    stored=c.core.read(folder/'parsed.json')
    assert all(actual[k]==stored[k] for k in ('record','usage','response_model','raw_response_sha256'))
    return actual


def collect(phase,effort,items):
    found=BASE_COLLECT(phase,effort,items)
    if phase=='controls' and effort=='none' and (PROBE_ROOT/'parsed.json').exists():
        item=next((i for i in items if i['sample_id']=='TC_correct'),None)
        if item and item['sample_id'] not in found:
            actual=verify(PROBE_ROOT,item,effort)
            found[item['sample_id']]=actual['record']
            terra.s.save(c.ROOT/'control_reuse.json',dict(source=str(PROBE_ROOT.relative_to(c.core.DEFAULT_RUN)),response_sha256=c.core.sha(PROBE_ROOT/'response.txt'),original_probe_preserved=True,selection='earliest_valid_response'))
    return found


def rejection(raw):return None


def attempt(folder,item,effort,registry,protocol_path,transport_amendment_path=None):
    folder.mkdir(parents=True,exist_ok=False)
    profile,req,count=request(item,effort)
    metadata=dict(request=req,profile=profile,request_sha256=digest(req['body']),packet_item_sha256=digest(item),input_token_estimate=count,protocol_sha256=c.core.sha(protocol_path))
    if transport_amendment_path:metadata['transport_amendment_sha256']=c.core.sha(transport_amendment_path)
    terra.s.save(folder/'request.json',metadata)
    key=registry.private_key('gpt_sol');session=requests.Session();session.trust_env=False
    state=dict(status='unknown',started_utc=terra.s.now(),post_maybe_sent=False,model='gpt-6.1-terra',effort=effort,actual_cost='Unknown')
    terra.s.save(folder/'status.json',state)
    start=time.monotonic()
    try:
        state['post_maybe_sent']=True
        response=session.post(req['url'],json=req['body'],headers={'Authorization':'Bearer '+key,'Accept':'application/json'},timeout=(15,120),allow_redirects=False)
        (folder/'response.txt').write_text(response.text.replace(key,'[REDACTED]'),encoding='utf-8')
        state.update(http_status=response.status_code,headers={k:v for k,v in response.headers.items() if k.lower() in ('x-request-id','content-type','retry-after')})
        if response.status_code!=200:state.update(status='http_error',reason='http_'+str(response.status_code))
        else:
            parsed=c.core.parse_current(profile,response.json(),item)
            terra.s.save(folder/'parsed.json',parsed)
            state.update(status='valid',response_model=parsed['response_model'],usage=parsed['usage'])
    except Exception as exc:
        state.update(error_type=type(exc).__name__,reason=str(exc).replace(key,'[REDACTED]')[:400])
    finally:
        session.close();state.update(completed_utc=terra.s.now(),seconds=round(time.monotonic()-start,3));terra.s.save(folder/'status.json',state)
    return state


def configure():
    c.ROOT=PROBE_ROOT/'validation'
    c.PROTOCOL=c.core.DEFAULT_RUN/'release/protocol/terra_foreground_validation.json'
    c.TRANSPORT_AMENDMENT=c.core.DEFAULT_RUN/'release/protocol/terra_foreground_transport.json'
    c.stream=sys.modules[__name__];c.collect=collect


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--execute',action='store_true');args=parser.parse_args()
    configure();print(json.dumps(c.run(args.execute)))
