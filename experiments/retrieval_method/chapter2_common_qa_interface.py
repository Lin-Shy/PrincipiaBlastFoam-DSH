"""Identical model-facing retrieval capabilities; backend identity stays internal."""
from copy import deepcopy
import json

SEARCH_DESCRIPTION='在固定的blastFoam原始资料中检索问题所需的说明或配置；返回带原始路径和行号的证据，可自主补充查询。'
POLICY='neutral_shared_search_v1'


def neutral_messages(messages):
    value=deepcopy(messages)
    if not value or value[0].get('role')!='system':raise ValueError('Common system message required')
    content=value[0]['content'];marker='\n可用工具：'
    if marker not in content:raise ValueError('Bound common tool specification missing')
    prefix,encoded=content.split(marker,1)
    specs,end=json.JSONDecoder().raw_decode(encoded)
    if not isinstance(specs,list):raise ValueError('Tool specification must be a list')
    if specs:
        if {s.get('name') for s in specs}!={'catalog','read_source','search'}:raise ValueError('Unexpected common retrieval interface')
        for spec in specs:
            if spec['name']=='search':spec['description']=SEARCH_DESCRIPTION
    value[0]['content']=prefix+marker+json.dumps(specs,ensure_ascii=False,separators=(',',':'))+encoded[end:]
    return value


class NeutralToolClient:
    def __init__(self,client):self.client=client;self.deployment=client.deployment
    def __call__(self,body,turn):
        return self.client({**body,'messages':neutral_messages(body['messages'])},turn)
