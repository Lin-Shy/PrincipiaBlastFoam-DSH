"""Separate same-byte transport recovery audit; never overwrites old QA runs."""
import argparse
import hashlib
import json
from pathlib import Path
from chapter2_autonomous_qa import RecordedQwenClient,read,save,wire
from chapter2_qwen_proxy_config import settings

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--original-request',type=Path,required=True)
    p.add_argument('--proxy-settings',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();base,key=settings(a.proxy_settings)
    from chapter2_knowledge_input_guard import install
    install()
    original=read(a.original_request)
    if original['status']!='transport_error' or any(e.get('usage') for e in original['events']):
        raise ValueError('only unresolved transport requests without successful usage may be recovered')
    body=original['request'];fingerprint=hashlib.sha256(wire(body).encode('utf-8')).hexdigest()
    if fingerprint!=original['request_sha256']:raise ValueError('original request drift')
    if original['endpoint']!=base+'/chat/completions':raise ValueError('provider endpoint changed; explicit amendment required')
    if a.output.exists():raise FileExistsError('new transport recovery revision required')
    save(a.output/'amendment.json',{'schema':'same_byte_qa_transport_recovery_v1',
      'original_request_file_sha256':hashlib.sha256(a.original_request.read_bytes()).hexdigest(),
      'request_sha256':fingerprint,'model':body['model'],'endpoint':original['endpoint'],
      'reason':'three original same-request attempts ended in transport errors; later independent availability diagnostic',
      'original_result_overwritten':False,'new_attempt_limit':3,'content_retries':0,'formal_result':False,
      'tls_version':'TLSv1.2','certificate_verification':True,'transport_route':'direct_https_to_registered_api_endpoint'})
    result=RecordedQwenClient(original['endpoint'],key,a.output/'requests')(body,1)
    response=result.get('response',{})
    summary={'status':result['status'],'attempts':len(result['events']),'response_model':response.get('model'),
      'expected_model':body['model'],'exact_model_match':response.get('model')==body['model'],
      'usage':response.get('usage'),'http_codes':[e.get('code') for e in result['events']],
      'formal_result':False}
    save(a.output/'summary.json',summary);print(json.dumps(summary))

if __name__=='__main__':main()
