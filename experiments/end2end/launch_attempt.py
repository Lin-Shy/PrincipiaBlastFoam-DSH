"""Operator launcher: one native DSH attempt under an explicit request grant.

No implicit key/config fallback and no automatic retries or resumption. A JSON
grant records an operator decision; it is not a security boundary against same UID.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from urllib.parse import urlsplit
from prepare_system_comparison import common_environment,write
from runtime_config import prepare as prepare_boot,runtime_node
from model_budget import Gate,serve,upstream
from collect_attempt_cost import collect

def check(pair,arm,binding,grant):
    if arm not in ['general','professional']:raise ValueError('unknown arm')
    manifest_hash=hashlib.sha256((pair/'manifest.json').read_bytes()).hexdigest()
    if grant.get('live_model_allowed') is not True or arm not in grant.get('arms',[]):raise PermissionError('no scoped model authorization')
    if grant.get('pair_manifest_sha256')!=manifest_hash or not grant.get('authorization_evidence'):raise PermissionError('authorization not bound to this pair')
    if grant.get('isolation_accepted') is not True or not grant.get('isolation_evidence'):raise PermissionError('runtime isolation not accepted')
    if grant.get('budget_unit')!='requests':raise PermissionError('this launcher enforces request-count budgets only; other budgets need enforcement before use')
    for key in ['max_requests_per_arm','max_output_tokens','wall_seconds']:
        if type(grant.get(key))!=int or grant[key]<1:raise PermissionError('explicit positive '+key+' required')
    if binding.get('model')!=grant.get('model') or binding.get('context_window')!=grant.get('context_window'):raise PermissionError('model/context grant mismatch')
    if type(binding.get('context_window'))!=int or binding['context_window']<=grant['max_output_tokens']:raise ValueError('invalid context bound')
    if binding.get('base_url_source')!='dedicated_file':
        parsed=urlsplit(binding['base_url'])
        if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password:raise ValueError('HTTPS endpoint without embedded credential required')
    elif not binding.get('endpoint_sha256') or binding['endpoint_sha256']!=grant.get('endpoint_sha256'):
        raise PermissionError('dedicated endpoint identity not bound to grant')
    if not binding.get('runtime') or not binding.get('credential_file'):raise ValueError('operator runtime and credential file binding required')
    if grant.get('complete_task_required') and not binding.get('cluster'):raise PermissionError('complete task requires scoped cluster service binding')
    if grant.get('complete_task_required'):
        if not grant.get('cluster_authorization_evidence'):raise PermissionError('no linked cluster authorization')
        import cluster_job
        c=binding['cluster'];cluster_job.plan(c['config'],c['run_id'])
        cluster_job.authorize(c['config'],c['grant'],c['run_id'],'submit')

def run(pair,arm,binding,grant):
    pair=pair.resolve();check(pair,arm,binding,grant)
    root=pair/arm;runtime=Path(binding['runtime']).resolve()
    if (root/'attempt_intent.json').exists():raise FileExistsError('attempt already reserved; no implicit resume')
    from snapshot_runtime import verify
    verify(runtime)
    # Immutable generated inputs before starting any provider request.
    manifest=json.loads((pair/'manifest.json').read_text(encoding='utf-8'))
    for name,expected in manifest['source_sha256'].items():
        if hashlib.sha256(Path(name).read_bytes()).hexdigest()!=expected:raise ValueError('prepared source changed; prepare new pair')
    credentials={}
    for line in Path(binding['credential_file']).read_text(encoding='utf-8-sig').splitlines():
        if line.strip() and not line.lstrip().startswith('#') and '=' in line:
            key,value=line.split('=',1);credentials[key.strip()]=value.strip().strip('"').strip("'")
    endpoint=credentials.get('CHAPTER3_BASE_URL','') if binding.get('base_url_source')=='dedicated_file' else binding['base_url']
    parsed=urlsplit(endpoint)
    if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password:raise ValueError('dedicated HTTPS endpoint invalid')
    if binding.get('base_url_source')=='dedicated_file' and hashlib.sha256(endpoint.rstrip('/').encode()).hexdigest()!=binding['endpoint_sha256']:raise PermissionError('dedicated endpoint changed')
    if credentials.get('CHAPTER3_BASE_URL','').rstrip('/')!=endpoint.rstrip('/') or credentials.get('CHAPTER3_MODEL')!=binding['model']:raise PermissionError('dedicated credential destination mismatch')
    key=credentials.get('CHAPTER3_API_KEY')
    if not key:raise PermissionError('dedicated Chapter3 key unavailable')
    lock=runtime.parent/'chapter3-model.lock'
    with lock.open('x',encoding='utf-8') as f:json.dump({'pid':os.getpid(),'arm':arm,'pair':str(pair)},f)
    server=None;cluster_server=None;started=time.time();exit_code=None
    try:
        write(root/'attempt_intent.json',{'arm':arm,'authorization':grant,'start_unix':started})
        write(root/'workspace/common/limits.json',{'model_requests':grant['max_requests_per_arm'],'max_output_tokens_per_request':grant['max_output_tokens'],'model_concurrency':1,'wall_seconds':grant['wall_seconds'],'native_retries':0,'cluster_run_id':binding.get('cluster',{}).get('run_id'),'no_new_job_on_disconnect':True})
        gate=Gate(root/'provider_ledger',binding['model'],grant['max_requests_per_arm'],grant['max_output_tokens'],upstream(endpoint,key,min(grant['wall_seconds'],180)),grant.get('generation'))
        server=serve(gate)
        patch=[{'id':'llm-pi-ai','disabled':False,'config':{'providers':{'chapter3-approved':{
            'api':'openai-completions','apiKeyEnv':'C3_GATE_TOKEN','baseURL':f'http://127.0.0.1:{server.server_port}/v1',
            'models':[{'id':binding['model'],'contextWindow':binding['context_window'],'maxTokens':grant['max_output_tokens'],'input':['text']}],
            'compat':binding.get('compat',{}),'timeoutMs':180000,'retryPolicy':{'mode':'normal','maxRetries':0}}}}},
            {'id':'agent-default-model','config':{'provider':'chapter3-approved','model':binding['model']}}]
        write(root/'approved.patch.yml',patch);prepare_boot(root,runtime)
        env=common_environment(root);env['C3_GATE_TOKEN']=gate.token
        if binding.get('cluster'):
            from cluster_service import Service,serve as serve_cluster
            cluster=binding['cluster']
            cluster_service=Service(root/'workspace',root/'operator_cluster',cluster['config'],cluster['grant'],cluster['run_id'])
            cluster_server=serve_cluster(cluster_service)
            # Service capability only; upstream SSH credentials stay in operator config.
            env['C3_CLUSTER_ENDPOINT']=f'http://127.0.0.1:{cluster_server.server_port}'
            env['C3_CLUSTER_TOKEN']=cluster_service.token
        command=[runtime_node(runtime),str(Path(__file__).with_name('native_attempt.mjs')),str(root),str(runtime),str(root/'approved.patch.yml'),str(root/'prompt.txt')]
        with (root/'attempt.stdout').open('xb') as out,(root/'attempt.stderr').open('xb') as err:
            try:exit_code=subprocess.run(command,cwd=root/'workspace',env=env,stdout=out,stderr=err,timeout=grant['wall_seconds']).returncode
            except subprocess.TimeoutExpired:exit_code='timeout'
        write(root/'native_cost.json',collect([root/'home/sessions']) if (root/'home/sessions').exists() else {'coverage':'no_sessions_found','complete_billing':None})
    finally:
        if server:
            gate.closed=True
            server.shutdown();server.server_close()
        if cluster_server:cluster_server.shutdown();cluster_server.server_close()
        try:write(root/'attempt_exit.json',{'exit_code':exit_code,'wall_seconds':time.time()-started,'engineering_success':'requires_external_review','remote_jobs':'reconcile receipts; model exit does not cancel them','provider_inflight':'inspect ledger reservations; cleanup is not cancellation proof'})
        finally:lock.unlink()
    return exit_code

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--pair',type=Path,required=True);p.add_argument('--arm',choices=['general','professional'],required=True)
    p.add_argument('--binding',type=Path,required=True);p.add_argument('--authorization',type=Path,required=True);a=p.parse_args()
    import sys
    code=run(a.pair,a.arm,json.loads(a.binding.read_text(encoding='utf-8')),json.loads(a.authorization.read_text(encoding='utf-8')))
    print(code);sys.exit(0 if code==0 else 1)
