"""Frozen offline deepseek-flash calls for dataset authoring and audits."""
from pathlib import Path
import hashlib
import json
import os
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

MODEL='deepseek-flash'
ENDPOINT='https://api.deepseek.com/chat/completions'

def wire(v):
    return json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'))

def sha(v):
    return hashlib.sha256(v).hexdigest()

def read(p):
    return json.loads(p.read_text(encoding='utf-8'))

def save(p,v):
    p.parent.mkdir(parents=True,exist_ok=True)
    tmp=p.with_suffix('.tmp')
    tmp.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');tmp.replace(p)

def key_from_config(dsh_home):
    key=os.environ.get('DEEPSEEK_API_KEY')
    if not key and dsh_home:
        import yaml
        conf=yaml.safe_load((dsh_home/'.credentials.yaml').read_text(encoding='utf-8'))
        key=conf.get('refs',{}).get('DEEPSEEK_API_KEY')
    if not isinstance(key,str) or not key.strip():
        raise ValueError('offline DeepSeek credential unavailable')
    return key.strip()

def call(identity,body,output,key,parser):
    assert body['model']==MODEL
    path=output/'responses'/(identity+'.json')
    fingerprint=sha(wire(body).encode('utf-8'))
    old=read(path) if path.exists() else None
    if old:
        if old['request_sha256']!=fingerprint:
            raise ValueError('request changed: a new authoring/audit revision is required')
        if old['status'] in ('response','invalid_response','http_rejected'):
            return old
        if old['status']=='in_flight':
            raise RuntimeError('unresolved live request: inspect authoritative process before recovery')
    events=old['events'] if old else []
    row={'id':identity,'request_sha256':fingerprint,'request':body,'events':events,'status':'prepared'}
    for attempt in range(len(events),3):
        started=time.monotonic()
        event={'attempt':attempt+1,'started_unix':time.time(),'status':'in_flight','usage':None}
        events.append(event);row['status']='in_flight';save(path,row)
        try:
            req=Request(ENDPOINT,data=wire(body).encode('utf-8'),headers={'Content-Type':'application/json','Authorization':'Bearer '+key})
            with urlopen(req,timeout=180) as response:
                raw=response.read().decode('utf-8')
            row['raw_response_text']=raw
            event.update(status='response',seconds=time.monotonic()-started)
            try:
                value=json.loads(raw);row['response']=value;event['usage']=value.get('usage')
                if value.get('model')!=MODEL:
                    raise ValueError('offline response model is not exact deepseek-flash')
                if value['choices'][0].get('finish_reason')!='stop':
                    raise ValueError('offline response did not finish normally')
                row['parsed']=parser(json.loads(value['choices'][0]['message']['content']),body)
                row['status']='response'
            except (ValueError,KeyError,TypeError,AssertionError) as exc:
                row.update(status='invalid_response',error=str(exc))
            save(path,row);return row
        except HTTPError as exc:
            retry=exc.code==429 or exc.code>=500
            event.update(status='http_error',code=exc.code,seconds=time.monotonic()-started)
            row['status']='transport_error' if retry else 'http_rejected';save(path,row)
            if not retry:return row
        except (URLError,TimeoutError,ConnectionError) as exc:
            event.update(status='transport_error',error_type=type(exc).__name__,seconds=time.monotonic()-started)
            row['status']='transport_error';save(path,row)
        if attempt<2:time.sleep(2**attempt)
    return row
