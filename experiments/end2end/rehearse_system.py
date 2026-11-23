"""Actual native DSH headless + deterministic loopback model. No real inference/solver.

Only fixed read/skill/write calls are emitted. Every request/response is retained.
This is integration acceptance, not engineering-task or scientific success.
"""
import argparse
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
from pathlib import Path
import subprocess
import threading
import time
from prepare_system_comparison import prepare,common_environment,write,WS
from collect_attempt_cost import collect

def rehearse(destination):
    prepare(destination,dump=True)
    results=[]
    for arm in ['general','professional']:
        root=destination/arm;network=root/'mock_transport';network.mkdir()
        requests=[];failures=[]
        actions=[('read',{'file_path':'task/request.md','limit':8}),
                 ('skill',{'name':'blastfoam-professional'}) if arm=='professional' else ('read',{'file_path':'task/conditions.json','limit':8}),
                 ('write',{'file_path':'rehearsal.txt','content':'OFFLINE_INTEGRATION_ONLY\nNo simulation was performed.\n'})]
        def fake_reply(body):
            seq=len(requests);requests.append(body)
            write(network/f'request-{seq:02d}.json',body)
            if seq>3:raise ValueError('unexpected request count')
            chunks=[{'id':f'mock-{seq}','object':'chat.completion.chunk','model':'offline-fixture','choices':[{'index':0,'delta':{'role':'assistant'},'finish_reason':None}]}]
            if seq<len(actions):
                name,args=actions[seq]
                offered=[t.get('function',{}).get('name') for t in body.get('tools',[])]
                if name not in offered:failures.append('missing tool '+name)
                delta={'tool_calls':[{'index':0,'id':f'call-{seq}','type':'function','function':{'name':name,'arguments':json.dumps(args)}}]}
                reason='tool_calls'
            else:delta={'content':'Offline integration completed; no simulation success claimed.'};reason='stop'
            chunks.extend([{'id':f'mock-{seq}','object':'chat.completion.chunk','model':'offline-fixture','choices':[{'index':0,'delta':delta,'finish_reason':None}]},
                {'id':f'mock-{seq}','object':'chat.completion.chunk','model':'offline-fixture','choices':[{'index':0,'delta':{},'finish_reason':reason}]},
                {'id':f'mock-{seq}','object':'chat.completion.chunk','model':'offline-fixture','choices':[],'usage':{'prompt_tokens':100,'completion_tokens':20,'total_tokens':120}}])
            raw=(''.join('data: '+json.dumps(c)+'\n\n' for c in chunks)+'data: [DONE]\n\n').encode()
            (network/f'response-{seq:02d}.sse').write_bytes(raw)
            return raw
        from model_budget import Gate,serve
        gate=Gate(root/'request_gate','offline-fixture',4,1024,fake_reply)
        server=serve(gate)
        patch=[{'id':'llm-pi-ai','disabled':False,'config':{'providers':{'chapter3-offline':{'api':'openai-completions','apiKeyEnv':'C3_OFFLINE_KEY','baseURL':f'http://127.0.0.1:{server.server_port}/v1','models':[{'id':'offline-fixture','contextWindow':131072,'maxTokens':1024,'input':['text']}],'retryPolicy':{'mode':'normal','maxRetries':0},'timeoutMs':20000}}}},
               {'id':'agent-default-model','config':{'provider':'chapter3-offline','model':'offline-fixture'}}]
        write(root/'mock.patch.yml',patch)
        env=common_environment(root);env['C3_OFFLINE_KEY']=gate.token
        (root/'mock_prompt.txt').write_text('Perform the fixed offline integration rehearsal. Do not run a solver or contact a remote host.',encoding='utf-8')
        import os
        runtime=Path(os.environ.get('DSH_CHECKOUT',str(WS.parent/'deepseek-harness')))
        from runtime_config import prepare as prepare_boot,runtime_node
        prepare_boot(root,runtime)
        command=[runtime_node(runtime),str(Path(__file__).with_name('native_attempt.mjs')),str(root),str(runtime),str(root/'mock.patch.yml'),str(root/'mock_prompt.txt')]
        started=time.monotonic()
        try:
            with (root/'headless.stdout').open('wb') as out,(root/'headless.stderr').open('wb') as err:
                process=subprocess.run(command,cwd=root/'workspace',env=env,stdout=out,stderr=err,timeout=75)
            code=process.returncode
        except subprocess.TimeoutExpired:
            code='timeout';failures.append('headless timeout')
        finally:
            server.shutdown();server.server_close()
        ledger=collect([root/'home/sessions']) if (root/'home/sessions').exists() else None
        if ledger:write(root/'mock_cost.json',ledger)
        result={'arm':arm,'exit_code':code,'loopback_requests':len(requests),'port':server.server_port,
            'artifact_exists':(root/'workspace/rehearsal.txt').exists(),'failures':failures,'wall_seconds':time.monotonic()-started,
            'real_model_calls':0,'remote_calls':0,'solver_runs':0,'simulation_success':False}
        write(root/'rehearsal_result.json',result);results.append(result)
        print(json.dumps(result),flush=True)
    write(destination/'rehearsal_results.json',results)
    if any(r['exit_code']!=0 or r['failures'] or not r['artifact_exists'] or r['loopback_requests']!=4 for r in results):raise RuntimeError('rehearsal failed; all evidence retained')

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('destination',type=Path);a=p.parse_args();rehearse(a.destination.resolve())
