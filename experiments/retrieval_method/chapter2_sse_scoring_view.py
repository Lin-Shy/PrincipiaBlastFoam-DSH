"""Expose verified logical requests to unchanged v7; retain wire receipts on disk."""
from copy import deepcopy
from pathlib import Path
import hashlib
import json
from chapter2_sse_record_transport import wire

POLICY='verified_logical_request_view_for_sse_scoring_v1'

def logical_view(record,body,folder,turn):
    logical=deepcopy(body)
    expected={**deepcopy(logical),'stream':True,'stream_options':{'include_usage':True}}
    digest=lambda value:hashlib.sha256(wire(value)).hexdigest()
    if (record.get('logical_request')!=logical or record.get('request')!=expected
        or record.get('logical_request_sha256')!=digest(logical)
        or record.get('request_sha256')!=digest(expected)):
        raise ValueError('SSE scoring logical/wire request mismatch')
    folder=Path(folder);physical=folder/f'{turn:02d}.json'
    if json.loads(physical.read_text(encoding='utf-8'))!=record:
        raise ValueError('SSE scoring physical receipt mismatch')
    raw=(folder/record['raw_sse_file']).resolve()
    if raw.parent!=folder.resolve() or hashlib.sha256(raw.read_bytes()).hexdigest()!=record['raw_response_sha256']:
        raise ValueError('SSE scoring raw stream mismatch')
    if record['status']=='response':
        if record.get('sse_done') is not True or record.get('canonical_response_sha256')!=digest(record['response']):
            raise ValueError('SSE scoring canonical response mismatch')
    return {**record,'request':logical,'request_sha256':digest(logical),
            'physical_request':deepcopy(record['request']),
            'physical_request_sha256':record['request_sha256'],
            'physical_receipt_sha256':hashlib.sha256(physical.read_bytes()).hexdigest(),
            'scoring_request_view_policy':POLICY}

class LogicalScoringClient:
    def __init__(self,client):self.client=client
    def __getattr__(self,name):return getattr(self.client,name)
    def __call__(self,body,turn):
        record=self.client(body,turn)
        return logical_view(record,body,self.client.folder,turn)

def install(router):
    if getattr(router,'_logical_scoring_view_installed',False):raise ValueError('Scoring logical view already installed')
    original=router.routed_client
    def routed(*args,**kwargs):
        if kwargs.get('workload')!='bulk':raise ValueError('SSE scoring view requires bulk deployment')
        return LogicalScoringClient(original(*args,**kwargs))
    router.routed_client=routed;router._logical_scoring_view_installed=True
