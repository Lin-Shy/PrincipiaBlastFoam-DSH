"""Central Chapter 2 entry point: preflight and one-shot metered connectivity.

No automatic retries, model substitution, audit release or Test execution.
The Dev120 payload is derived from the registry and the existing frozen runner.
"""
import runtime_layout as layout
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
import os
from pathlib import Path
import sys

PROJECT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT / 'src'))
from principia_core.config.llm import Registry, ConfigurationBlocked, financial_gate
from judge_api_adapter import usage

WORKSPACE = PROJECT.parent
DEFAULT_RUN = WORKSPACE / 'graduation-experiment-results/chapter2_retrieval'


def now():return datetime.now(timezone.utc).isoformat()
def sha(path):return hashlib.sha256(layout.resolve(path).read_bytes()).hexdigest()
def read(path):return json.loads(layout.resolve(path).read_text(encoding='utf-8-sig'))
def save(path, obj):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf-8') as f:
        json.dump(obj,f,ensure_ascii=False,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())


@contextmanager
def exclusive_lock(path):
    with path.open('x',encoding='utf-8') as f:
        f.write(str(os.getpid()));f.flush();os.fsync(f.fileno())
    try:yield
    finally:path.unlink()


def check_registry(registry):
    records=[]
    for key in registry.execution['probe_order']:
        row=dict(model_key=key,status='not_sent',requests_sent=0,problems=[])
        try:
            route=registry.resolve(key)
            row.update(api_model_id=route['api_model_id'],endpoint=route['endpoint'],protocol=route['protocol'],
                       requested_parameters=route['wire_parameters'],deployment_version=route['deployment_version'])
        except ConfigurationBlocked as exc:row['problems'].append(str(exc))
        try:financial_gate(registry.stage('connectivity_'+key))
        except ConfigurationBlocked as exc:row['problems'].append(str(exc))
        try:
            row['credential']=registry.credential_status(key)
            if not row['credential']['present']:row['problems'].append('credential_missing:'+row['credential']['variable'])
        except ConfigurationBlocked as exc:row['problems'].append(str(exc))
        row['status']='blocked_before_network' if row['problems'] else 'ready_for_explicit_execute'
        records.append(row)
    other=[]
    for stage in ['dev120','calibration_gpt_astra_first','calibration_deepseek_first','calibration_qwen3_14b_first']:
        try:financial_gate(registry.stage(stage));problem=None
        except ConfigurationBlocked as exc:problem=str(exc)
        other.append(dict(stage=stage,problem=problem,scope_authorized=registry.stage(stage)['scope_authorized']))
    return dict(schema='ch2_central_preflight_v1',created_utc=now(),model_requests_sent=0,
                records=records,following_stage_gates=other,
                status='blocked' if any(r['problems'] for r in records) else 'ready_for_connectivity_only',
                source_sha256=registry.hashes,dev120_started=False,audit_released=False)


def probe_body(registry, key):
    route=registry.resolve(key)
    prompt='Return exactly one JSON object {"ok":true}. No other text.'
    body={'model':route['api_model_id'],'stream':False,**route['wire_parameters']}
    limit=registry.execution['probe_output_token_cap']
    if route['protocol']=='responses':body.update(input=[{'role':'user','content':prompt}],max_output_tokens=limit,store=False)
    else:body.update(messages=[{'role':'user','content':prompt}],max_tokens=limit)
    return route,body


def check_probe_response(route,raw):
    if raw.get('model') not in route['allowed_response_model_ids']:
        raise ValueError('model_identity_mismatch')
    if route['protocol']=='responses':
        if raw.get('status')!='completed' or raw.get('error') or raw.get('incomplete_details'):
            raise ValueError('incomplete_or_refused_response')
        chunks=[]
        for item in raw.get('output',[]):
            if item.get('type')=='reasoning':continue
            if item.get('type')!='message' or item.get('role')!='assistant':raise ValueError('unexpected_output_item')
            for p in item.get('content',[]):
                if p.get('type')!='output_text':raise ValueError('nontext_or_refusal')
                chunks.append(p['text'])
        text=''.join(chunks)
        effort=raw.get('reasoning',{}).get('effort')
        mode='low_echoed' if effort=='low' else 'parameter_accepted_effect_not_echoed'
    else:
        choices=raw.get('choices',[])
        if len(choices)!=1 or choices[0].get('finish_reason')!='stop':raise ValueError('truncated_or_multiple_choices')
        msg=choices[0]['message']
        if msg.get('refusal') or msg.get('tool_calls'):raise ValueError('unexpected_refusal_or_tool')
        if msg.get('reasoning_content'):raise ValueError('thinking_returned_despite_nonthinking_request')
        text=msg.get('content');mode='nonthinking_observed'
    if not isinstance(text,str) or json.loads(text)!={'ok':True}:raise ValueError('unexpected_minimal_output_format')
    u=usage(raw,route['protocol'])
    if route['protocol']=='chat_completions' and u['reasoning_tokens'] not in [None,0]:
        raise ValueError('thinking_tokens_despite_nonthinking_request')
    return dict(status='passed_minimal_response',response_model=raw['model'],usage=u,
                system_fingerprint=raw.get('system_fingerprint'),response_id=raw.get('id'),
                reasoning_control_evidence=mode,wire_parameters_accepted=True,
                reasoning_control_confirmed=mode in ['low_echoed','nonthinking_observed'],
                deployment_version_verified=False)


def one_probe(registry,key,out,run=None):
    """Financial validation precedes credential access and ALL HTTP setup."""
    stage=registry.stage('connectivity_'+key);budget=financial_gate(stage)
    if stage['max_physical_requests']!=1 or stage['max_sessions']!=1:
        raise ConfigurationBlocked('minimal_probe_scope_must_be_one_request')
    route,body=probe_body(registry,key)
    token_in=registry.execution['probe_input_token_cap'];token_out=registry.execution['probe_output_token_cap']
    cost=None
    if budget.get('control_mode')!='owner_authorized_request_quota_v1':
        cost=(Decimal(token_in)*Decimal(str(budget['input_price_per_million']))+Decimal(token_out)*Decimal(str(budget['output_price_per_million'])))/Decimal(1000000)
        if cost>Decimal(str(budget['hard_limit'])):raise ConfigurationBlocked('reservation_exceeds_approved_limit')
    secret=registry.private_key(key)
    claim=(run or DEFAULT_RUN)/'active_execution_requests/connectivity'/(key+'.claim.json')
    claim.parent.mkdir(parents=True,exist_ok=True)
    save(claim,dict(status='reserved_single_owner_authorized_attempt',output_directory=str(out),
        model_key=key,registry_sha256=registry.hashes,started_utc=now()))
    folder=out/'connectivity'/key;folder.mkdir(parents=True,exist_ok=True)
    if (folder/'request.json').exists() or (folder/'reservation.json').exists():
        raise ConfigurationBlocked('prior_attempt_exists_no_retry')
    save(folder/'request.json',dict(url=route['endpoint'],body=body,config_sha256=registry.hashes))
    event=dict(stage='connectivity_'+key,started_utc=now(),reserved_cost=str(cost) if cost is not None else 'Unknown',currency=budget['currency'],
               attempts=1,request_sha256=sha(folder/'request.json'),input_cap=token_in,output_cap=token_out)
    save(folder/'reservation.json',event)
    with (out/'request_ledger.jsonl').open('a',encoding='utf-8') as f:
        f.write(json.dumps(event)+'\n');f.flush();os.fsync(f.fileno())
    # Exactly one direct request; no redirects, inherited proxies or transport retries.
    from urllib.request import Request,build_opener,ProxyHandler,HTTPRedirectHandler,HTTPSHandler
    from urllib.error import HTTPError
    class NoRedirect(HTTPRedirectHandler):
        def redirect_request(self,*args,**kwargs):return None
    import ssl
    context=ssl.create_default_context()
    if route['provider']=='qwen_proxy':
        context.minimum_version=context.maximum_version=ssl.TLSVersion.TLSv1_2
    result=dict(status='transport_not_completed',requests_sent=1)
    try:
        request=Request(route['endpoint'],data=json.dumps(body).encode('utf-8'),
                        headers={'Authorization':'Bearer '+secret,'Content-Type':'application/json'})
        with build_opener(ProxyHandler({}),HTTPSHandler(context=context),NoRedirect()).open(request,timeout=registry.execution['probe_timeout_seconds']) as response:
            rawtext=response.read().decode('utf-8')
            headers={k:v for k,v in response.headers.items() if k.lower() in ['date','x-request-id','request-id']}
            http_status=response.status
        # All persisted response objects derive from redacted text, even on malformed JSON.
        safe=rawtext.replace(secret,'[REDACTED]')
        with (folder/'response.txt').open('x',encoding='utf-8') as f:f.write(safe)
        raw=json.loads(safe);save(folder/'response.json',raw)
        result=check_probe_response(route,raw);result.update(requests_sent=1,http_status=http_status,response_headers=headers,
            provider_cost={k:raw[k] for k in ('cost','billing','cost_details') if k in raw} or 'Unknown')
        if result['usage']['input_tokens']>token_in or result['usage']['output_tokens']>token_out:
            result['status']='provider_exceeds_reserved_token_cap_stop'
    except HTTPError as exc:result=dict(status='http_rejected_stop_no_retry',http_status=exc.code,requests_sent=1)
    except (OSError,TimeoutError) as exc:
        reason=getattr(exc,'reason',exc)
        local_denied=isinstance(reason,PermissionError) and getattr(reason,'winerror',None)==10013
        result=dict(status='local_socket_denied_before_http' if local_denied else 'transport_error_stop_no_retry',
            error_type=type(exc).__name__,requests_sent=0 if local_denied else 1,
            transport_attempts=1,errno=getattr(reason,'errno',None),winerror=getattr(reason,'winerror',None))
    except (ValueError,KeyError,TypeError) as exc:
        # Fixed exception class only: never log provider-echoed messages or secrets.
        result=dict(status='invalid_response_stop_no_retry',error_type=type(exc).__name__,requests_sent=1)
    result.update(completed_utc=now(),reservation_retained=True,request_sha256=sha(folder/'request.json'))
    save(folder/'validation.json',result)
    return result


def prepare_dev120(registry,run,out):
    """Snapshot config without authorizing network or altering prior artifacts."""
    old=run/'experiments/agentic/reused_inputs'
    cfg=read(old/'generation_config.pending.json');g=registry.generation
    m=registry.resolve(g['initial_model'])
    cfg.update(api_model_id=m['api_model_id'],expected_response_model_id=m['allowed_response_model_ids'][0],
               endpoint=m['endpoint'],api_key_environment_variable=m['key_env'],
               api_authorized=False,budget=registry.stage('dev120')['financial'],
               registry_source_sha256=registry.hashes,wire_parameters=m['wire_parameters'])
    for key in ['combined_context_tokens','concurrency','model_budget','knowledge_budget','max_physical_requests_per_session','max_physical_requests_total','transport_attempts','content_retries']:
        cfg[key]=g[key]
    if cfg['split_freeze_sha256']!=g['split_freeze_sha256']:raise ConfigurationBlocked('frozen_split_mismatch')
    cfg['status']='central_config_draft_not_approved_for_network'
    save(out/'dev120.central_config.draft.json',cfg)
    # Use the existing bound runner only for deterministic preflight.
    import dev120_runner
    dev120_runner.preflight(out/'dev120.central_config.draft.json')
    save(out/'dev120.offline_preflight.json',dict(status='passed',sessions=120,old_answers_reused=False,
        config_sha256=sha(out/'dev120.central_config.draft.json'),registry_sha256=registry.hashes,
        model_requests_sent=0,financial_gate_passed=False))


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config-dir',type=Path)
    p.add_argument('--run-dir',type=Path,default=DEFAULT_RUN);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--execute-connectivity',action='store_true')
    a=p.parse_args();registry=Registry(a.config_dir) if a.config_dir else Registry()
    out=a.out.resolve();run=a.run_dir.resolve()
    if not out.is_relative_to(run):raise ValueError('Output must be inside the independent experiment')
    out.mkdir(parents=True,exist_ok=False)
    save(out/'config_snapshot.json',registry.snapshot())
    report=check_registry(registry);save(out/'connectivity_preflight.json',report)
    # Keep a persistent ledger even when it has zero physical requests.
    with (out/'request_ledger.jsonl').open('x',encoding='utf-8'):pass
    save(out/'ledger_status.json',dict(status='not_started',physical_requests=0,reserved_cost='0',currency=None))
    prepare_dev120(registry,run,out)
    if report['status']=='blocked':
        save(out/'STOP.json',dict(status='blocked_before_first_model_request',reason='budget_or_credentials_or_route',
            requests_sent=0,dev120_sessions_started=0,ai_calibration_records=0,audit_released=False,
            owner_scope_authorized=True,financial_approval_present=False))
        print(json.dumps(dict(status='blocked_before_network',requests_sent=0,report=str(out/'connectivity_preflight.json'))))
        return 2
    if not a.execute_connectivity:
        print(json.dumps(dict(status='dry_run_ready',requests_sent=0)));return 0
    with exclusive_lock(run/'central_execution.lock'):
        results={}
        for key in registry.execution['probe_order']:
            result=one_probe(registry,key,out,run);results[key]=result
        passed=all(r['status']=='passed_minimal_response' and r.get('reasoning_control_confirmed') for r in results.values())
        save(out/'connectivity_results.json',dict(status='passed' if passed else 'partial_or_failed',models=results,dev120_started=False,
            next_gate='Dev120 must consume hash-bound approved config and budget; not launched by connectivity command'))
    return 0 if passed else 3


if __name__=='__main__':raise SystemExit(main())
