"""Attach a source-checked phase declaration, without inferring task intent."""
import copy
import hashlib
import json
import re


def phase_identity(engine,packet):
    path=packet['case']+'/constant/phaseProperties'
    if path not in engine.graph['inventory']:return None
    root=(engine.skill/'corpus').resolve();file=(root/path).resolve()
    if not file.is_relative_to(root):raise ValueError('identity source escapes corpus')
    raw=file.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=engine.graph['inventory'][path]:raise ValueError('identity source changed')
    import knowledge as k
    entries,diagnostics=k.parse_dictionary(raw.decode())
    if diagnostics:return None
    selected=[e for e in entries if e['key']=='phases' and '/' not in e['dictionary_path']]
    if len(selected)!=1 or not selected[0]['resolved']:return None
    entry=selected[0]
    match=re.fullmatch(r'\(\s*([A-Za-z_]\w*(?:\s+[A-Za-z_]\w*)*)\s*\)',entry['value'])
    if not match:return None
    phases=match[1].split()
    if len(set(phases))!=len(phases):return None
    return {'phases':phases,'source':{'path':path,'entry':'phases','start':entry['line_start'],'end':entry['line_end']},'sha256':engine.graph['inventory'][path]}


def attach_identity(packet,identity,budget):
    if identity is None:return packet
    result=copy.deepcopy(packet);result['case_identity']=identity
    wire=lambda p:json.dumps(p,ensure_ascii=False,separators=(',',':'))
    if len(wire(result))<=budget:return result
    result.pop('query_expansion',None)
    if len(wire(result))<=budget:return result
    # Preserve paths, bindings, conditions and edits; shorten only source excerpts.
    while len(wire(result))>budget:
        locations=[p for p in result.get('locations',[]) if p.get('text')]
        if not locations:
            # The indexed source reader still exposes the verified file digest.
            if 'sha256' in result['case_identity']:
                result['case_identity'].pop('sha256');continue
            return packet
        item=max(locations,key=lambda p:len(p['text']))
        overflow=len(wire(result))-budget+20
        item['text']=item['text'][:-min(len(item['text']),overflow)];item['complete']=False
    return result
