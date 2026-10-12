"""Retain explicit caller-provided task context separately from retrieval phrasing."""
import copy,hashlib,json


def locate_with_context(locate,query,tutorial_case,translation,budget,original_request=''):
    if not original_request:return locate(query,tutorial_case,translation,budget)
    if not isinstance(original_request,str) or len(original_request)>32768 or not original_request.strip():
        raise ValueError('invalid original request')
    # Rewritten text can introduce a source model ('const -> sutherland')
    # that the lexical ranker mistakes for the destination. Until hint roles
    # are structured, retain query/translation in the call audit only.
    packet=copy.deepcopy(locate(original_request,tutorial_case,'',budget))
    packet['original_request_sha256']=hashlib.sha256(original_request.encode()).hexdigest()
    identity=packet.get('case_identity',{})
    target=packet.get('target_resolution',{})
    if identity.get('sha256') and identity.get('sha256')==target.get('sha256') and identity.get('source',{}).get('path')==target.get('source'):
        identity.pop('sha256') # Same file proof remains in target_resolution.
    wire=lambda p:len(json.dumps(p,ensure_ascii=False,separators=(',',':')))
    while wire(packet)>budget:
        excerpts=[x for x in packet.get('locations',[]) if x.get('text')]
        if not excerpts:return {'status':'insufficient_context_budget','locations':[], 'original_request_sha256':packet['original_request_sha256']}
        item=max(excerpts,key=lambda x:len(x['text']))
        item['text']=item['text'][:-min(len(item['text']),wire(packet)-budget+20)]
        item['complete']=False
    return packet
