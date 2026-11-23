"""Resume the verified A01 session at seq 106; preserve all original receipts."""
import ctypes
import json
import os
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from cluster_first import (HERE, base, batch, runtime, read, sha, write, common_environment,
    launch_attempt, cluster_service, Reviewed, RetryGate, snapshot_runtime, runtime_digest)

def main():
    root=batch/'cluster_live/CH3-DEV-A01/general'
    close=read(root/'request14_closeout.json')
    hist=read(root/'provider_ledger/ledger.json')['events']
    assert len(hist)==14 and hist[-1]['state']=='reserved' and close['retransmit'] is False
    trace=[json.loads(row)['event'] for row in (root/'native_events.jsonl').read_bytes().splitlines()]
    calls=Counter(e['data']['callId'] for e in trace if e['type']=='tool/call')
    results=Counter(e['data']['message']['source']['callId'] for e in trace if e['type']=='tool/result')
    assert calls==results and all(v==1 for v in calls.values())
    assert trace[-1]['seq']==106 and trace[-1]['type']=='step/start'
    assert not list((root/'operator_cluster').iterdir())
    snapshot_runtime.sha=runtime_digest
    snapshot_runtime.verify(runtime)
    assert all(sha(Path(p))==h for p,h in read(root.parent/'manifest.json')['source_sha256'].items())
    prior=read(batch/'cluster_live/authorization_change_20261119/host_reconciliation.json')
    for name,h in prior['hashes'].items():
        assert sha(Path('\\\\?\\'+str((root/name).resolve())))==h
    proto=base/'pilot_decision_20261117'
    binding=read(proto/'general.binding.json')
    grant=read(root/'attempt_intent.json')['authorization']
    grant['max_requests_per_arm']=read(batch/'authorization.json')['cluster']['requests_per_arm']
    assert grant['max_requests_per_arm']==100
    dest=root/'continuation-01'
    dest.mkdir(exist_ok=False)
    lock=runtime.parent/'chapter3-model.lock'
    old=read(lock)
    assert old['pid']==39164 and Path(old['pair'])==root.parent and old['arm']=='general'
    handle=ctypes.windll.kernel32.OpenProcess(0x1000,False,old['pid'])
    if handle or ctypes.windll.kernel32.GetLastError()!=87:raise RuntimeError('cannot prove original PID absent')
    lock.rename(dest/'previous_lock.json')
    write(lock,dict(pid=os.getpid(),arm='general',pair=str(root.parent)))
    server=bridge=None
    try:
        creds=dict(line.split('=',1) for line in Path(binding['credential_file']).read_text(encoding='utf-8-sig').splitlines() if '=' in line and not line.lstrip().startswith('#'))
        endpoint=creds['CHAPTER3_BASE_URL'].strip().strip('"').rstrip('/')
        import hashlib
        assert hashlib.sha256(endpoint.encode()).hexdigest()==grant['endpoint_sha256']
        assert creds['CHAPTER3_MODEL'].strip().strip('"')==grant['model']
        gate=RetryGate(dest/'provider_ledger',grant['model'],100,grant['max_output_tokens'],launch_attempt.upstream(endpoint,creds['CHAPTER3_API_KEY'].strip().strip('"'),180),grant['generation'])
        gate.events.extend(hist)
        gate.events[-1]=dict(hist[-1],state='closed_usage_unknown',resolution='request14_closeout.json')
        gate.save();server=launch_attempt.serve(gate)
        patch=read(root/'approved.patch.yml')
        patch[0]['config']['providers']['chapter3-approved']['baseURL']=f'http://127.0.0.1:{server.server_port}/v1'
        write(dest/'overlay.json',patch)
        c=read(proto/'acceptance.config.json');c['wall_minutes']=90
        rid='c3-dev-a01-general-first-20261119'
        g=dict(live_actions_allowed=True,actions=['stage','submit','status','collect'],run_ids=[rid],limits={k:c[k] for k in ['tasks','wall_minutes','memory_mib']})
        service=Reviewed(root/'workspace',dest/'operator_cluster',c,g,rid);bridge=cluster_service.serve(service)
        env=dict(common_environment(root),C3_PYTHON=sys.executable,C3_MODULE_PATH=str(HERE.parent),C3_RUNTIME=str(runtime),
            C3_GATE_TOKEN=gate.token,C3_CLUSTER_ENDPOINT=f'http://127.0.0.1:{bridge.server_port}',C3_CLUSTER_TOKEN=service.token)
        msg='宿主在原会话第14步等待响应时中断。继续原任务，之前已完成的工具动作不重复。总请求上限100，已占14；集群额度不变，尚无提交意图或JobID。'
        (dest/'continuation.txt').write_text(msg,encoding='utf8')
        write(dest/'intent.json',dict(session=close['session_id'],seq=106,request_offset=14,remaining=86,tool_results=sum(results.values()),time=time.time()))
        limits=root/'workspace/common/limits.json'
        settings=read(limits);write(dest/'original_limits.json',settings)
        settings.update(model_requests=100,already_counted_at_resume=14)
        tmp=limits.with_suffix('.next');write(tmp,settings);tmp.replace(limits)
        cmd=[launch_attempt.runtime_node(runtime),str(HERE/'native_resume.mjs'),str(root),str(runtime),str(dest/'overlay.json'),str(dest/'continuation.txt')]
        start=time.time()
        with (dest/'stdout.log').open('xb') as out,(dest/'stderr.log').open('xb') as err:
            code=subprocess.run(cmd,cwd=root/'workspace',env=env,stdout=out,stderr=err,timeout=max(1,grant['wall_seconds']-600)).returncode
        write(dest/'exit.json',dict(code=code,wall_seconds=time.time()-start))
        return code
    finally:
        for srv in (bridge,server):
            if srv:srv.shutdown();srv.server_close()
        if read(lock)['pid']==os.getpid():lock.unlink()

if __name__=='__main__':sys.exit(main())
