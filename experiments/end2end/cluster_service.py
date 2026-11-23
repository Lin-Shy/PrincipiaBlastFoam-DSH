"""Operator-side wrapper for one fixed owned run; no arbitrary SSH/shell endpoint."""
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import shutil
import threading
import time
import cluster_job

class Service:
    def __init__(self,workspace,state,config,grant,run_id):
        self.workspace=Path(workspace).resolve();self.state=Path(state).resolve()
        self.state.mkdir(parents=True,exist_ok=False)
        self.config=config;self.grant=grant;self.run_id=run_id
        self.token=secrets.token_urlsafe(32);self.lock=threading.Lock()
    def execute(self,body):
        if set(body)-{'action','payload'}:raise ValueError('unexpected operation fields')
        action=body.get('action')
        if action not in ['plan','stage','submit','status','collect']:raise ValueError('unsupported action')
        payload=self.workspace/body.get('payload','payload')
        if not payload.resolve().is_relative_to(self.workspace):raise ValueError('payload outside task workspace')
        if not self.lock.acquire(blocking=False):raise ValueError('operation already in flight')
        event={'action':action,'run_id':self.run_id,'start_unix':time.time()}
        try:
            if action=='collect' and (self.state/'collection_receipt.json').exists():
                result=cluster_job.load(self.state/'collection_receipt.json')
                if cluster_job.digest(self.state/'collected.tar')!=result['archive_sha256']:raise ValueError('cached collection changed')
            else:result=cluster_job.run(action,self.config,self.run_id,self.state,payload,self.grant)
            if action=='collect':
                returned=self.workspace/'returned';returned.mkdir(exist_ok=True)
                if returned.is_symlink() or getattr(returned.lstat(),'st_file_attributes',0)&1024:raise ValueError('return directory link refused')
                target=returned/'collected.tar'
                if target.exists():
                    if cluster_job.digest(target)!=result['archive_sha256']:raise ValueError('returned archive changed')
                else:
                    with target.open('xb') as out,(self.state/'collected.tar').open('rb') as source:shutil.copyfileobj(source,out)
                result={**result,'archive_in_workspace':'returned/collected.tar'}
            event.update(status='returned',result=result);return result
        except Exception as error:event.update(status='failed',error_type=type(error).__name__);raise
        finally:
            event['end_unix']=time.time()
            with (self.state/'operations.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(event)+'\n')
            self.lock.release()

def serve(service):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            if self.path!='/action' or self.headers.get('Authorization')!='Bearer '+service.token:self.send_error(403);return
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<=8192:raise ValueError('invalid request size')
                result=service.execute(json.loads(self.rfile.read(size)));raw=json.dumps(result).encode()
                self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
            except Exception as error:
                raw=json.dumps({'status':'failed_or_unknown','error_type':type(error).__name__,'instruction':'inspect operator receipts; do not infer solver state'}).encode()
                self.send_response(409);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start();return server
