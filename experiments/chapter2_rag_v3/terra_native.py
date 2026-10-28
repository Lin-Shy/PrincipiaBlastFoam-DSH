"""Native Responses SSE candidate, bypassing the proxy's chat conversion route."""
from copy import deepcopy
import json
import terra_stream as chat
from judge_api_adapter import digest

terra=chat.terra
CHAT_REQUEST=chat.request


def request(item,effort):
    profile,req,count=CHAT_REQUEST(item,effort)
    profile=deepcopy(profile);req=deepcopy(req)
    profile.update(protocol='responses')
    profile['wire_parameters']={'reasoning':{'effort':effort}}
    old=req['body']
    # Identical task content, expressed in the provider's declared native envelope.
    req['body']=dict(model=old['model'],input=old['messages'],stream=True,store=False,
                     max_output_tokens=6144,reasoning={'effort':effort})
    req['url']=profile['base_url'].rstrip('/')+'/responses'
    req.update(profile_sha256=digest(profile),request_sha256=digest(req['body']))
    return profile,req,count


def normalize(raw,allowed):
    completed=None;identity=None;models=set()
    for block in raw.replace('\r\n','\n').split('\n\n'):
        data='\n'.join(line[5:].lstrip(' ') for line in block.splitlines() if line.startswith('data:'))
        if not data or data=='[DONE]':continue
        event=json.loads(data)
        if event.get('error') or event.get('type')=='error':raise ValueError('provider_native_error')
        response=event.get('response')
        if isinstance(response,dict):
            if response.get('model'):models.add(response['model'])
            if models-set(allowed):raise ValueError('model_identity_mismatch')
            rid=response.get('id')
            if identity and rid and identity!=rid:raise ValueError('stream_response_identity_changed')
            if rid:identity=rid
        if event.get('type')=='response.completed':
            if completed is not None:raise ValueError('multiple_completed_responses')
            completed=response
    if not completed:raise ValueError('native_stream_incomplete')
    if completed.get('model') not in allowed:raise ValueError('model_identity_mismatch')
    if completed.get('status')!='completed':raise ValueError('Incomplete/refused response')
    if not isinstance(completed.get('usage'),dict):raise ValueError('usage_unknown_stop_and_reconcile')
    return completed


def rejection(raw):
    models=set();errors=[]
    try:
        for block in raw.replace('\r\n','\n').split('\n\n'):
            data='\n'.join(line[5:].lstrip(' ') for line in block.splitlines() if line.startswith('data:'))
            if not data or data=='[DONE]':continue
            x=json.loads(data);response=x.get('response') or {}
            if response.get('model'):models.add(response['model'])
            if x.get('model'):models.add(x['model'])
            if x.get('type') in ('response.output_text.delta','response.completed','response.refusal.delta'):return None
            if x.get('error'):errors.append(x['error'])
            elif x.get('type')=='error':errors.append(x)
    except (ValueError,TypeError):return None
    if models!={'gpt-6.1-terra'} or len(errors)!=1:return None
    e=errors[0]
    if any(word in str(e.get('message','')).lower() for word in ('overloaded','rate limit')):
        return dict(type=e.get('type'),message=e.get('message'),grade_content_received=False,response_model='gpt-6.1-terra')
    return None


def install():
    # The metered transport and raw preservation are shared. Only envelope/parser differ.
    chat.request=request;chat.normalize=normalize;chat.rejection=rejection


def attempt(*args,**kwargs):return chat.attempt(*args,**kwargs)
def verify(*args,**kwargs):return chat.verify(*args,**kwargs)
