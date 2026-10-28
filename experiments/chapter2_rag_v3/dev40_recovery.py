"""One owner-authorized replay of the original, unanswered connection refusal.

No content retry, model substitution, or overwriting of the baseline attempt.
The exact saved wire body and frozen autonomous-agent parser are reused.
"""
from copy import deepcopy
import hashlib
import http.client
import json
from pathlib import Path
import time
from urllib.parse import urlsplit

from central_execution import DEFAULT_RUN,Registry,now,read,sha,save,exclusive_lock
import dev40_optimization as dev


def active_recovery(root=None):
    root=Path(root) if root is not None else dev.ROOT
    file=root/'infrastructure_recovery.json'
    if not file.exists():return None
    receipt=read(file)
    if receipt.get('status')!='completed':return None
    if (receipt['config_id'],receipt['question_id'],receipt['maximum_physical_requests'])!=(
            'qwen3_8b__direct__no_tools','E17-02',1):raise ValueError('Unapproved recovery scope')
    if sha(root/receipt['baseline_file'])!=receipt['baseline_sha256'] or sha(root/receipt['result_file'])!=receipt['result_sha256']:
        raise ValueError('Recovery evidence binding changed')
    return receipt


def execute():
    from dev40_runner import prepare,update
    spec,questions=prepare();root=dev.ROOT
    baseline=root/'generation/qwen3_8b__direct__no_tools/E17-02/result.json'
    old=read(baseline);saved=read(baseline.parent/'requests/00.request.json')
    if old['status']!='transport_error' or old['actual_completion_tokens']!=0 or len(old['turns'])!=1:
        raise ValueError('Only the original unanswered infrastructure failure can be recovered')
    if old['turns'][0]['response']!={'status':'transport_error','error_type':'ConnectionRefusedError'}:
        raise ValueError('Recovery requires a proven connection refusal')
    if list((baseline.parent/'requests').glob('*.response.txt')):raise ValueError('A model response was already received')
    folder=root/'generation_recovery/qwen3_8b__direct__no_tools/E17-02'
    receipt_file=root/'infrastructure_recovery.json'
    if receipt_file.exists():
        if active_recovery(root):print('Existing single recovery retained; no request repeated',flush=True);return
        raise ValueError('Partial recovery exists; reconcile without resending')
    registry=Registry();route=registry.resolve('qwen3_8b');secret=registry.private_key('qwen3_8b')
    if route['api_model_id']!=saved['body']['model'] or route['endpoint']!='http://192.168.31.205:8001/v1/chat/completions':
        raise ValueError('Recovery route/model drift')
    assert saved['input_tokens_estimated']+saved['body']['max_tokens']<=32768
    question=next(q['question'] for q in questions if q['id']=='E17-02')
    from principia_core.retrieval.knowledge_agent import AutonomousKnowledgeAgent,ModelBudget
    from principia_core.retrieval.knowledge_qa import KnowledgeToolSession
    receipt=dict(created_utc=now(),status='started',owner_instruction='2026-10-25: one separately recorded recovery allowed for proven unanswered infrastructure failure',
        config_id=old['config_id'],question_id=old['id'],baseline_file=baseline.relative_to(root).as_posix(),baseline_sha256=sha(baseline),
        result_file=(folder/'result.json').relative_to(root).as_posix(),maximum_physical_requests=1,
        selection_policy='Use this single recovery regardless of its status; never select the better answer',
        original_execution_sha256=sha(root/'execution.json'),endpoint_migration_sha256=sha(root/'endpoint_migration.json'),
        source_sha256=sha(Path(__file__)),exact_wire_body_reused=True,content_retries=0)
    def count(messages):
        if messages!=old['turns'][0]['request']['messages']:raise ValueError('Recovery agent prompt drift')
        return old['turns'][0]['counted_input_tokens']
    def client(body,turn):
        if turn!=0 or body!=old['turns'][0]['request']:raise ValueError('Recovery logical request drift')
        payload=deepcopy(saved['body']);save(folder/'requests/00.request.json',dict(saved,url=route['endpoint']))
        event=dict(started_utc=now(),config_id=old['config_id'],question_id=old['id'],turn=0,model_key='qwen3_8b',
            kind='infrastructure_recovery',recovery_attempt=1,baseline_sha256=receipt['baseline_sha256'],endpoint=route['endpoint'],actual_cost='Unknown')
        with (root/'request_ledger.jsonl').open('a',encoding='utf8') as stream:stream.write(json.dumps(event)+'\n')
        address=urlsplit(route['endpoint']);conn=http.client.HTTPConnection(address.hostname,address.port,timeout=15)
        try:
            conn.connect();conn.sock.settimeout(240)
            conn.request('POST',address.path,body=json.dumps(payload,ensure_ascii=False).encode(),headers={'Authorization':'Bearer '+secret,'Content-Type':'application/json'})
            response=conn.getresponse();text=response.read().decode('utf8').replace(secret,'[REDACTED]')
            (folder/'requests/00.response.txt').write_text(text,encoding='utf8')
            if response.status!=200:return dict(status='http_rejected',http_status=response.status)
            raw=json.loads(text)
            if raw.get('model') not in route['allowed_response_model_ids']:return dict(status='model_identity_mismatch',raw_response=raw)
            usage=raw.get('usage',{})
            if any(type(usage.get(k)) is not int or usage[k]<0 for k in ('prompt_tokens','completion_tokens')):return dict(status='usage_unknown',raw_response=raw)
            if usage['prompt_tokens']+usage['completion_tokens']>32768 or usage['completion_tokens']>payload['max_tokens']:return dict(status='provider_budget_violation',raw_response=raw)
            return dict(status='response',raw_response=raw,response=dict(raw,model=old['model']),actual_api_model=route['api_model_id'],request=payload)
        except (OSError,http.client.HTTPException) as exc:return dict(status='transport_error',error_type=type(exc).__name__)
        except (ValueError,KeyError,TypeError) as exc:return dict(status='invalid_response',error_type=type(exc).__name__)
        finally:conn.close()
    with exclusive_lock(root/'recovery.lock'):
        if folder.exists():raise ValueError('Recovery folder exists; never overwrite or resend')
        folder.mkdir(parents=True);save(receipt_file,receipt);start=time.monotonic()
        result=AutonomousKnowledgeAgent(old['model'],KnowledgeToolSession('none'),client,count,ModelBudget(**old['model_budget'])).run(question)
        result.update(id=old['id'],arm=old['arm'],config_id=old['config_id'],actual_api_model=route['api_model_id'],actual_endpoint=route['endpoint'],
            execution_sha256=sha(root/'execution.json'),question_sha256=hashlib.sha256(question.encode()).hexdigest(),
            split_freeze_sha256=spec['split_freeze_sha256'],delivered_lines=[],attempt_kind='infrastructure_recovery',
            baseline_sha256=receipt['baseline_sha256'],completed_utc=now(),seconds=round(time.monotonic()-start,3))
        save(folder/'result.json',result);receipt.update(status='completed',completed_utc=now(),result_sha256=sha(folder/'result.json'),recovery_status=result['status'])
        update(receipt_file,receipt)
    print(json.dumps(dict(recovery_status=result['status'],original_failure_preserved=True,physical_requests=1)),flush=True)
