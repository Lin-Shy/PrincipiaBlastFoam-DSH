"""Explicit three-model services and preserved, credential-free request records."""
from dataclasses import dataclass,field
from pathlib import Path
from copy import deepcopy
from datetime import datetime,timezone
from urllib.request import Request,build_opener,ProxyHandler,HTTPSHandler
from urllib.error import HTTPError
from urllib.parse import urlsplit
import base64,hashlib,json,ssl,threading,time

WORK=Path(__file__).resolve().parents[3]
EXPERIMENT=WORK/'graduation-experiment-results/chapter2_retrieval'
MODELS=('qwen3-8b','qwen3-14b','llama3.1-8b')
def encoded(value):return (json.dumps(value,ensure_ascii=False,indent=2,allow_nan=False)+'\n').encode()
def sha(data):return hashlib.sha256(data).hexdigest()
def now():return datetime.now(timezone.utc).isoformat()
def strict_json(data):
    def pairs(items):
        obj={}
        for k,v in items:
            if k in obj:raise ValueError('Duplicate JSON field')
            obj[k]=v
        return obj
    def invalid(value):raise ValueError('Non-finite JSON number')
    return json.loads(data,object_pairs_hook=pairs,parse_constant=invalid)
def settings(path):
    values={}
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        line=line.strip()
        if line and not line.startswith('#') and '=' in line:
            k,v=line.split('=',1);values[k.strip()]=v.strip().strip('"').strip("'")
    return values

@dataclass(frozen=True)
class Deployment:
    logical_model:str
    model:str
    endpoint:str=field(repr=False)
    key:str=field(repr=False)
    concurrency:int=1
    context_tokens:int=32768

def load_model(logical_model,*,concurrency=None):
    if logical_model not in MODELS:raise ValueError('Unknown model')
    if logical_model=='qwen3-14b':
        v=settings(WORK/'PrincipiaBlastFoam-DSH/config/llm/.env')
        base=v['QWEN_PROXY_BASE_URL'];key=v['QWEN_PROXY_API_KEY'];name='qwen3-14b'
        maximum=int(v.get('QWEN_PROXY_MAX_CONCURRENCY','20'))
    else:
        v=settings(WORK/'.env.supercomputer')
        if logical_model=='qwen3-8b':
            base=v['QWEN_SUPERCOMPUTER_BASE_URL'];key=v['QWEN_SUPERCOMPUTER_API_KEY']
            name=v['QWEN_SUPERCOMPUTER_MODEL'];maximum=int(v.get('QWEN_SUPERCOMPUTER_MAX_CONCURRENCY','8'))
        else:
            base=v['LLAMA_8B_BASE_URL'];key=v['LLAMA_API_KEY'];name=v['LLAMA_8B_MODEL'];maximum=2
    base=base.rstrip('/');url=urlsplit(base)
    if url.scheme not in {'http','https'} or not url.hostname or url.username or url.password or url.query or url.fragment:raise ValueError('Invalid service address')
    if not key or not name:raise ValueError('Incomplete service configuration')
    endpoint=base if base.endswith('/chat/completions') else base+'/chat/completions'
    fingerprint=sha((endpoint+'\n'+name).encode())
    report=EXPERIMENT/'capacity'/logical_model/'summary.json'
    if logical_model!='qwen3-14b' and report.exists():
        saved=json.loads(report.read_text(encoding='utf-8'))
        if saved.get('deployment_sha256')==fingerprint and saved.get('status')=='measured':
            maximum=saved['recommended_concurrency']
    requested=maximum if concurrency is None else concurrency
    if type(requested) is not int or not 1<=requested<=maximum:raise ValueError('Concurrency exceeds measured/configured model limit')
    return Deployment(logical_model,name,endpoint,key,requested)

def public_deployment(d):
    return dict(logical_model=d.logical_model,api_model=d.model,endpoint_sha256=sha(d.endpoint.encode()),
                deployment_sha256=sha((d.endpoint+'\n'+d.model).encode()),concurrency=d.concurrency,context_tokens=d.context_tokens)

def payload(d,messages,max_tokens,temperature=0):
    messages=deepcopy(messages)
    body=dict(model=d.model,messages=messages,max_tokens=max_tokens,temperature=temperature,stream=False,response_format={'type':'json_object'})
    if d.logical_model=='qwen3-8b':
        for msg in reversed(messages):
            if msg['role']=='user':
                if not msg['content'].rstrip().endswith('/no_think'):msg['content']+='\n/no_think'
                break
    elif d.logical_model=='qwen3-14b':
        body['enable_thinking']=False
    return body

class Client:
    def __init__(self,deployment,timeout=180):
        self.deployment=deployment;self.timeout=timeout
        context=ssl.create_default_context()
        if deployment.logical_model=='qwen3-14b':context.minimum_version=context.maximum_version=ssl.TLSVersion.TLSv1_2
        self.opener=build_opener(ProxyHandler({}),HTTPSHandler(context=context))
        self.limiter=threading.BoundedSemaphore(deployment.concurrency)
        self.halted=threading.Event()

    def complete(self,body,path=None):
        if body.get('model')!=self.deployment.model or body.get('stream') is not False:raise ValueError('Request identity mismatch')
        row=dict(deployment=public_deployment(self.deployment),request=body,request_sha256=sha(encoded(body)),
                 started_utc=now(),status='in_flight',transport_attempts=0)
        if path:
            path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
            with path.open('xb') as stream:stream.write(encoded(row))
        queued=time.monotonic()
        with self.limiter:
            start=time.monotonic();row['queue_seconds']=start-queued
            received_body=None
            try:
                if self.halted.is_set():
                    row['status']='deployment_halted'
                    return self._finish(row,path,start)
                request=Request(self.deployment.endpoint,data=json.dumps(body,ensure_ascii=False).encode(),headers={'Authorization':'Bearer '+self.deployment.key,'Content-Type':'application/json'})
                row['transport_attempts']=1
                with self.opener.open(request,timeout=self.timeout) as response:
                    raw=response.read();row['http_status']=response.status
                received_body=raw
                if path:
                    wire_path=path.with_suffix('.response.bin')
                    with wire_path.open('xb') as stream:stream.write(raw)
                    row['response_body_file']=wire_path.name
                row['response_sha256']=sha(raw)
                value=strict_json(raw)
                row.update(raw_response=value,response_sha256=sha(raw))
                if value.get('model')!=self.deployment.model:
                    row['status']='model_identity_mismatch';self.halted.set()
                elif not isinstance(value.get('choices'),list) or len(value['choices'])!=1 or not isinstance(value['choices'][0].get('message',{}).get('content'),str):row['status']='invalid_response'
                else:row['status']='response'
            except HTTPError as exc:
                row.update(status='http_result_unknown' if exc.code>=500 else 'http_rejected',http_status=exc.code)
                # Keep server diagnostics locally; never print credentials/addresses.
                error=exc.read();row['error_response_sha256']=sha(error)
                try:
                    import re
                    safe=error.decode('utf-8').replace(self.deployment.key,'[redacted_credential]')
                    safe=re.sub(r'https?://[^\s"<>]+','[redacted_url]',safe)
                    row['error_response']=strict_json(safe)
                except (ValueError,UnicodeError):row['error_response_type']='non_json'
            except (OSError,ValueError,TypeError,AttributeError) as exc:
                if isinstance(exc,OSError) and received_body is not None:
                    # A local persistence error is not a network timeout. Preserve
                    # the exact received bytes in the durable JSON and never POST again.
                    row.update(status='response_persistence_error',error_type=type(exc).__name__,
                               response_sha256=sha(received_body),response_body_base64=base64.b64encode(received_body).decode('ascii'))
                    self.halted.set()
                else:row.update(status='outcome_unknown' if isinstance(exc,OSError) else 'invalid_response',error_type=type(exc).__name__)
            if row['status'] in {'outcome_unknown','http_result_unknown'}:self.halted.set()
        return self._finish(row,path,start)

    def _finish(self,row,path,start):
        row['seconds']=time.monotonic()-start;row['ended_utc']=now()
        if path:
            temp=path.with_suffix('.tmp');temp.write_bytes(encoded(row));temp.replace(path)
        return row
