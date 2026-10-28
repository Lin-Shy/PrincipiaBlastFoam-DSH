"""Terra candidate SSE transport. Raw chunks, usage and identity remain auditable."""
from copy import deepcopy
import hashlib
import http.client
import json
import ssl
import time
from urllib.parse import urlsplit
import test160_terra as terra
from judge_api_adapter import digest


def request(item, effort):
    if effort not in ('none','low','medium','high'):raise ValueError('Unapproved candidate')
    profile,req,count=terra.request('gpt_sol',item)
    profile=deepcopy(profile);req=deepcopy(req)
    profile.update(stream=True,wire_parameters=dict(profile['wire_parameters'],reasoning_effort=effort),output_token_cap=6144)
    req['body'].update(stream=True,stream_options={'include_usage':True},reasoning_effort=effort,max_completion_tokens=6144)
    assert count+6144<=32768
    req.update(profile_sha256=digest(profile),request_sha256=digest(req['body']))
    return profile,req,count


def normalize(raw,allowed):
    """Require a complete SSE stream; never invent missing model identity or usage."""
    content=[];models=set();ids=set();usage=None;finish=None;done=False;events=[]
    for block in raw.replace('\r\n','\n').split('\n\n'):
        data='\n'.join(line[5:].lstrip(' ') for line in block.splitlines() if line.startswith('data:'))
        if not data:continue
        if data=='[DONE]':done=True;continue
        event=json.loads(data);events.append(event)
        if event.get('error'):raise ValueError('provider_stream_error:'+str(event['error'].get('code','unknown')))
        if event.get('model'):models.add(event['model'])
        if event.get('id'):ids.add(event['id'])
        if models-set(allowed):raise ValueError('model_identity_mismatch')
        if len(ids)>1:raise ValueError('stream_response_identity_changed')
        if isinstance(event.get('usage'),dict):usage=event['usage']
        choices=event.get('choices',[])
        if len(choices)>1:raise ValueError('multiple_stream_choices')
        for choice in choices:
            if choice.get('index',0)!=0:raise ValueError('foreign_stream_choice')
            delta=choice.get('delta',{})
            if delta.get('tool_calls') or delta.get('function_call') or delta.get('refusal'):raise ValueError('Unexpected refusal/tool call')
            if delta.get('content') is not None:
                if not isinstance(delta['content'],str):raise ValueError('invalid_stream_content')
                content.append(delta['content'])
            if choice.get('finish_reason') is not None:finish=choice['finish_reason']
    if not done:raise ValueError('stream_incomplete_no_done')
    if len(models)!=1:raise ValueError('model_identity_missing')
    if usage is None:raise ValueError('usage_unknown_stop_and_reconcile')
    if finish!='stop':raise ValueError('Truncated/multiple response')
    return dict(id=next(iter(ids)) if ids else None,model=next(iter(models)),object='chat.completion',
        choices=[dict(index=0,message=dict(role='assistant',content=''.join(content)),finish_reason=finish)],usage=usage)


def rejection(raw):
    """A terminal provider overload before a final answer is known, not a timeout."""
    models=set();errors=[]
    try:
        for block in raw.replace('\r\n','\n').split('\n\n'):
            data='\n'.join(line[5:].lstrip(' ') for line in block.splitlines() if line.startswith('data:'))
            if not data or data=='[DONE]':continue
            x=json.loads(data)
            if x.get('model'):models.add(x['model'])
            if x.get('error'):errors.append(x['error'])
            for choice in x.get('choices',[]):
                delta=choice.get('delta',{})
                if any(delta.get(k) for k in ('content','refusal','tool_calls','function_call')) or choice.get('finish_reason')=='stop':return None
    except (ValueError,TypeError):return None
    if models!={'gpt-6.1-terra'} or len(errors)!=1:return None
    e=errors[0]
    if e.get('type')=='upstream_error' and any(word in str(e.get('message','')).lower() for word in ('overloaded','rate limit')):
        return dict(type=e['type'],message=e.get('message'),grade_content_received=False,response_model='gpt-6.1-terra')
    return None


def attempt(folder,item,effort,registry,protocol_path,transport_amendment_path=None):
    folder.mkdir(parents=True,exist_ok=False)
    profile,req,count=request(item,effort)
    metadata=dict(request=req,profile=profile,request_sha256=digest(req['body']),packet_item_sha256=digest(item),input_token_estimate=count,protocol_sha256=terra.s.sha(protocol_path),response_representation='response.sse is raw; response.txt is deterministic normalized JSON')
    if transport_amendment_path:metadata['transport_amendment_sha256']=terra.s.sha(transport_amendment_path)
    terra.s.save(folder/'request.json',metadata)
    state=dict(status='unknown',started_utc=terra.s.now(),phase='connecting',model='gpt-6.1-terra',effort=effort,post_maybe_sent=False,actual_cost='Unknown')
    key=registry.private_key('gpt_sol');url=urlsplit(req['url']);start=time.monotonic()
    conn=http.client.HTTPSConnection(url.hostname,url.port or 443,timeout=15,context=ssl.create_default_context())
    try:
        conn.connect();conn.sock.settimeout(600)
        state.update(phase='sending',post_maybe_sent=True)
        conn.request('POST',url.path,body=json.dumps(req['body'],ensure_ascii=False).encode('utf-8'),headers={'Authorization':'Bearer '+key,'Content-Type':'application/json','Accept':'text/event-stream','Connection':'close','User-Agent':'PrincipiaChapter2Judge/1'})
        response=conn.getresponse();state.update(http_status=response.status,phase='receiving',headers={k:v for k,v in response.getheaders() if k.lower() in ('content-type','x-request-id','x-oneapi-request-id','retry-after')})
        if response.status!=200:
            text=response.read().decode('utf-8').replace(key,'[REDACTED]')
            (folder/'response.error.txt').write_text(text,encoding='utf-8');state.update(status='http_error',reason='http_'+str(response.status))
        else:
            with (folder/'response.sse').open('wb') as f:
                while True:
                    line=response.readline()
                    if not line:break
                    f.write(line.replace(key.encode(),b'[REDACTED]'));f.flush()
            raw=(folder/'response.sse').read_text(encoding='utf-8')
            normalized=normalize(raw,profile['allowed_response_model_ids'])
            terra.s.save(folder/'response.txt',normalized)
            parsed=terra.scoring.parse_current(profile,normalized,item)
            parsed['stream_provenance']=dict(raw_sha256=terra.s.sha(folder/'response.sse'),normalized_sha256=terra.s.sha(folder/'response.txt'),normalization='strict_sse_v1')
            terra.s.save(folder/'parsed.json',parsed)
            state.update(status='valid',phase='complete',response_model=parsed['response_model'],usage=parsed['usage'])
    except Exception as exc:
        state.update(error_type=type(exc).__name__,reason=str(exc).replace(key,'[REDACTED]')[:400])
        if not state['post_maybe_sent']:state['status']='pre_send_failure'
        elif state.get('http_status')==200 and (folder/'response.sse').exists():state['status']='stream_unknown_or_invalid'
        if (folder/'response.sse').exists():
            rejected=rejection((folder/'response.sse').read_text(encoding='utf-8'))
            if rejected:
                state.update(status='provider_rejected',reason='explicit_stream_upstream_overload',provider_rejection=rejected)
    finally:conn.close()
    state.update(completed_utc=terra.s.now(),seconds=round(time.monotonic()-start,3))
    terra.s.save(folder/'status.json',state)
    return state


def verify(folder,item,effort):
    saved=terra.s.load(folder/'request.json');profile,req,count=request(item,effort)
    assert saved['request']==req and saved['profile']==profile
    raw=normalize((folder/'response.sse').read_text(encoding='utf-8'),profile['allowed_response_model_ids'])
    assert raw==terra.s.load(folder/'response.txt')
    actual=terra.scoring.parse_current(profile,raw,item);stored=terra.s.load(folder/'parsed.json')
    assert actual['record']==stored['record'] and actual['raw_response_sha256']==stored['raw_response_sha256']
    assert stored['stream_provenance']['raw_sha256']==terra.s.sha(folder/'response.sse')
    return actual
