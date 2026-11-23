"""Exercise the operator launcher with synthetic grants/credentials and fake transport.
No real credential file is read. The upstream function is replaced before run().
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import launch_attempt
from prepare_system_comparison import prepare,write

def rehearse(destination):
    runtime=Path(os.environ['DSH_CHECKOUT']).resolve()
    prepare(destination,True)
    credential=destination/'FAKE.env'
    credential.write_text('CHAPTER3_BASE_URL=https://offline.invalid/v1\nCHAPTER3_MODEL=offline-fixture\nCHAPTER3_API_KEY=FAKE-NOT-A-CREDENTIAL\n')
    results=[]
    for arm in ['general','professional']:
        calls=[]
        def fake(body):
            seq=len(calls);calls.append(body)
            if seq==0:delta={'tool_calls':[{'index':0,'id':'read-task','type':'function','function':{'name':'read','arguments':json.dumps({'file_path':'task/request.md','limit':5})}}]}
            elif seq==1:delta={'tool_calls':[{'index':0,'id':'write-proof','type':'function','function':{'name':'write','arguments':json.dumps({'file_path':'operator-rehearsal.txt','content':'Synthetic operator rehearsal only. No simulation.'})}}]}
            elif seq==2:delta={'content':'Operator rehearsal complete, no scientific success.'}
            else:raise ValueError('unexpected extra request')
            chunks=[{'id':f'offline-{seq}','object':'chat.completion.chunk','model':'offline-fixture','choices':[{'index':0,'delta':{'role':'assistant'},'finish_reason':None}]},
                {'id':f'offline-{seq}','object':'chat.completion.chunk','model':'offline-fixture','choices':[{'index':0,'delta':delta,'finish_reason':None}]},
                {'id':f'offline-{seq}','object':'chat.completion.chunk','model':'offline-fixture','choices':[{'index':0,'delta':{},'finish_reason':'stop' if seq==2 else 'tool_calls'}]},
                {'id':f'offline-{seq}','object':'chat.completion.chunk','model':'offline-fixture','choices':[],'usage':{'prompt_tokens':50,'completion_tokens':10,'total_tokens':60}}]
            return (''.join('data: '+json.dumps(c)+'\n\n' for c in chunks)+'data: [DONE]\n\n').encode()
        def replace_upstream(url,key,timeout):
            assert url=='https://offline.invalid/v1' and key=='FAKE-NOT-A-CREDENTIAL'
            return fake
        launch_attempt.upstream=replace_upstream
        binding={'runtime':str(runtime),'credential_file':str(credential),'base_url':'https://offline.invalid/v1','model':'offline-fixture','context_window':131072}
        grant={'live_model_allowed':True,'arms':[arm],'pair_manifest_sha256':hashlib.sha256((destination/'manifest.json').read_bytes()).hexdigest(),
            'authorization_evidence':'SYNTHETIC FIXTURE ONLY; no live authority','isolation_accepted':True,'isolation_evidence':'SYNTHETIC FIXTURE, fixed read/write only',
            'budget_unit':'requests','max_requests_per_arm':3,'max_output_tokens':1024,'wall_seconds':60,'model':'offline-fixture','context_window':131072}
        code=launch_attempt.run(destination,arm,binding,grant)
        outcome={'arm':arm,'exit_code':code,'synthetic_requests':len(calls),'artifact':(destination/arm/'workspace/operator-rehearsal.txt').exists(),'real_provider_calls':0,'solver_calls':0}
        results.append(outcome);print(json.dumps(outcome),flush=True)
        assert code==0 and len(calls)==3 and outcome['artifact']
        try:launch_attempt.run(destination,arm,binding,grant)
        except FileExistsError:pass
        else:raise AssertionError('duplicate attempt not denied')
    write(destination/'operator_rehearsal.json',{'results':results,'duplicate_attempt_denied':True,'grants_are_synthetic_not_authority':True})

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('destination',type=Path);a=p.parse_args();rehearse(a.destination.resolve())
