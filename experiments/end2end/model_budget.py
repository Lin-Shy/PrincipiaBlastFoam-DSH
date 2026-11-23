"""Serial OpenAI-compatible request gate used equally by both chapter arms.

Hard request-count/response-byte bounds and a requested output cap with violation
detection; bytes are not an input-token bound. Unknown usage closes the gate.
"""
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import threading
import time
import urllib.request

class Gate:
    def __init__(self,root,model,max_requests,max_output_tokens,forward,generation=None):
        if type(max_requests)!=int or max_requests<1 or type(max_output_tokens)!=int or max_output_tokens<1:raise ValueError('positive explicit limits required')
        self.root=Path(root);self.root.mkdir(parents=True,exist_ok=False)
        self.model=model;self.limit=max_requests;self.output=max_output_tokens;self.forward=forward
        self.generation=dict(generation or {});self.lock=threading.Lock();self.events=[];self.closed=False;self.token=secrets.token_urlsafe(32)
    def call(self,body):
        if not self.lock.acquire(blocking=False):raise ValueError('one in-flight request only')
        try:
            if self.closed or len(self.events)>=self.limit:raise ValueError('request gate closed/exhausted')
            if body.get('model')!=self.model:raise ValueError('model mismatch')
            body=dict(body);requested=body.pop('max_completion_tokens',body.get('max_tokens',self.output))
            if type(requested)!=int or requested<1:raise ValueError('invalid requested output bound')
            body.update(self.generation)
            body['max_tokens']=min(requested,self.output)
            body['stream']=True;body['stream_options']={'include_usage':True}
            i=len(self.events)+1;row={'request':i,'state':'reserved','start_unix':time.time(),'usage':None}
            self.events.append(row);self.save()
            (self.root/f'request-{i:04d}.json').write_text(json.dumps(body,ensure_ascii=False),encoding='utf-8')
            try:
                raw=self.forward(body)
                (self.root/f'response-{i:04d}.bin').write_bytes(raw)
                usages=[]
                for line in raw.decode('utf-8').splitlines():
                    if line.startswith('data:') and line[5:].strip()!='[DONE]':
                        value=json.loads(line[5:]);
                        if value.get('usage'):usages.append(value['usage'])
                if not usages:raise ValueError('provider usage missing')
                u=usages[-1]
                if any(type(u.get(k))!=int or u[k]<0 for k in ['prompt_tokens','completion_tokens','total_tokens']):raise ValueError('invalid usage')
                row.update(state='settled',usage=u)
                if u['completion_tokens']>body['max_tokens']:
                    row['state']='provider_limit_violation';self.closed=True
                return raw
            except Exception as error:
                row.update(state='unknown',error_type=type(error).__name__);self.closed=True;raise
            finally:row['end_unix']=time.time();self.save()
        finally:self.lock.release()
    def save(self):
        state={'model':self.model,'max_requests':self.limit,'per_request_output_tokens':self.output,'closed':self.closed,'events':self.events,'billing':'unknown unless provider invoice supplied'}
        pending=self.root/'ledger.tmp';pending.write_text(json.dumps(state,indent=2),encoding='utf-8');pending.replace(self.root/'ledger.json')

def serve(gate):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            if self.path!='/v1/chat/completions' or self.headers.get('Authorization')!='Bearer '+gate.token:
                self.send_error(403);return
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<=4_000_000:raise ValueError('request size')
                raw=gate.call(json.loads(self.rfile.read(size)))
                self.send_response(200);self.send_header('Content-Type','text/event-stream');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
            except Exception:
                self.send_error(429,'request not completed; inspect operator ledger')
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start();return server

def upstream(base_url,key,timeout):
    # Called only by the operator launcher after checking a scoped grant.
    def send(body):
        request=urllib.request.Request(base_url.rstrip('/')+'/chat/completions',data=json.dumps(body).encode(),headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
        with urllib.request.urlopen(request,timeout=timeout) as response:
            raw=response.read(32_000_001)
            if len(raw)>32_000_000:raise ValueError('response exceeds archival bound')
            return raw
    return send
