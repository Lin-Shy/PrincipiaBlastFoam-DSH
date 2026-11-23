"""Common agent-side client. Receives a local capability token, never an SSH key."""
import argparse
import json
import os
import urllib.request
from urllib.parse import urlsplit

def call(action,payload='payload'):
    endpoint=os.environ['C3_CLUSTER_ENDPOINT'];token=os.environ['C3_CLUSTER_TOKEN']
    parsed=urlsplit(endpoint)
    if parsed.scheme!='http' or parsed.hostname!='127.0.0.1':raise ValueError('operator loopback endpoint required')
    request=urllib.request.Request(endpoint+'/action',data=json.dumps({'action':action,'payload':payload}).encode(),headers={'Authorization':'Bearer '+token,'Content-Type':'application/json'})
    with urllib.request.urlopen(request,timeout=3700) as response:return json.load(response)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['plan','stage','submit','status','collect']);p.add_argument('--payload',default='payload');a=p.parse_args()
    print(json.dumps(call(a.action,a.payload),ensure_ascii=False,indent=2))
