"""Launch the explicitly approved 1400-session grid in sequential arm processes."""
import argparse
from collections import Counter
from datetime import datetime,timezone
import json
import os
import subprocess
import time

from common import *

def now():return datetime.now(timezone.utc).isoformat()

def write_status(root,status):
    temp=root/'live_status.tmp'
    temp.write_text(json.dumps(status,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    temp.replace(root/'live_status.json')

def progress(root,arms):
    result={}
    for arm in arms:
        folders=list((root/arm/'generation').glob('*/result.json'))
        counts=Counter();requests=0;usage_in=usage_out=unknown=0
        for file in folders:
            r=read(file);counts[r['status']]+=1
            for turn in r.get('turns',[]):
                requests+=1
                usage=turn.get('response',{}).get('response',{}).get('usage',{})
                if isinstance(usage.get('prompt_tokens'),int) and isinstance(usage.get('completion_tokens'),int):
                    usage_in+=usage['prompt_tokens'];usage_out+=usage['completion_tokens']
                else:unknown+=1
        result[arm]=dict(completed_sessions=len(folders),statuses=dict(counts),requests_in_completed_sessions=requests,
            input_tokens=usage_in,output_tokens=usage_out,unknown_usage=unknown,
            arm_completion=(root/arm/'completed.json').exists())
    return result

def verify_and_authorize(run_id):
    from e2e import ARMS
    protocol=ARCHIVE/'configs/e2e_14b_v1.json';p=read(protocol)
    if sha(protocol)!='f88294b47abb93df35aa892e0d3943a6791134c5a33a5e5707fcd3ce70d63a92':
        raise ValueError('approved protocol hash changed')
    for n,h in p['code'].items():
        if sha(HERE/n)!=h:raise ValueError('round2 frozen source drift')
    for n,h in p['legacy_code'].items():
        if sha(PROJECT/n)!=h:raise ValueError('legacy frozen source drift')
    bindings=[(QUESTIONS,p['questions_sha256']),(GRAPH,p['graph_sha256']),
        (RESOURCES/'source-map.json',p['source_map_sha256']),
        (ARCHIVE/'indexes/bge_dense_v1/manifest.json',p['bge_index_sha256']),
        (ARCHIVE/'indexes/bge_model_binding.json',p['bge_model_binding_sha256']),
        (RESOURCES/'tokenizers/qwen3-14b/artifact-binding.json',p['tokenizer_binding_sha256'])]
    for path,h in bindings:
        if sha(path)!=h:raise ValueError('frozen input identity drift')
    for n,h in read(RESOURCES/'source-map.json')['files'].items():
        if sha(RESOURCES/'corpus'/n)!=h:raise ValueError('frozen corpus file drift')
    index=ARCHIVE/'indexes/bge_dense_v1'
    if any(sha(index/n)!=h for n,h in read(index/'manifest.json')['files'].items()):
        raise ValueError('BGE vectors/passages drift')
    from chapter2_qwen_proxy_config import settings
    base,key=settings(WORKSPACE/'.env.qwen_proxy')
    if base+'/chat/completions'!=p['endpoint']:raise ValueError('configured endpoint differs from frozen protocol')
    del key
    if p['arms']!=ARMS or p['sessions']!=1400:raise ValueError('approved grid drift')
    if (ARCHIVE/'e2e_runs'/run_id).exists():raise FileExistsError('fresh run id required; never replay an existing batch')
    approval=ARCHIVE/'authorizations'/(run_id+'_generation.json')
    save(approval,dict(approved=True,protocol_sha256=sha(protocol),scope='generation',max_sessions=1400,
        user_instruction='确认启动会话',context='User confirmed the immediately preceding proposal: seven14B groups x200=1400 generation sessions, including400 paired graph/BM25 reference reruns. Paid judging and holdout require separate approval.',
        approved_recorded_utc=now(),run_id=run_id,answer_model='qwen3-14b',provider='qwen_proxy',
        endpoint=p['endpoint'],scoring_approved=False,holdout_approved=False,
        actual_proxy_price_and_quota='not supplied; unknown disclosed before user confirmation'))
    save(ARCHIVE/'audit'/(run_id+'_preflight.json'),dict(passed=True,protocol_sha256=sha(protocol),
        frozen_round2_code=len(p['code']),frozen_legacy_code=len(p['legacy_code']),corpus_files=479,
        index_verified=True,endpoint_matches=True,credential_present=True,credentials_recorded=False,
        paid_requests=0,checked_utc=now(),approval_sha256=sha(approval)))
    return approval

def run(run_id,approval):
    from e2e import approval_check
    protocol=ARCHIVE/'configs/e2e_14b_v1.json';p=approval_check(approval,protocol)
    root=ARCHIVE/'e2e_runs'/run_id;root.mkdir(parents=True,exist_ok=False)
    (root/'logs').mkdir();runtime=root/'controller_runtime';runtime.mkdir()
    for name in ['launch_controller.py','launch_worker.py']:(runtime/name).write_bytes((HERE/name).read_bytes())
    save(root/'execution_manifest.json',dict(started_utc=now(),controller_pid=os.getpid(),run_id=run_id,
        generation_protocol_sha256=sha(protocol),approval_sha256=sha(approval),arms=p['arms'],sessions=1400,
        execution_mode='sequential arms, one active generation process; no retries/replays or automatic scoring',
        controller_sha256=sha(HERE/'launch_controller.py'),worker_sha256=sha(HERE/'launch_worker.py'),
        execution_note='Between-session guard stops after recorded auth/quota/rate or identity rejection, or3 consecutive transport failures. Saves failed result first. No prompt/tool/model/budget modification.'))
    for arm in p['arms']:
        with (root/'logs'/(arm+'.stdout.log')).open('x',encoding='utf-8') as out,(root/'logs'/(arm+'.stderr.log')).open('x',encoding='utf-8') as err:
            process=subprocess.Popen([sys.executable,'-X','utf8','-u',str(HERE/'launch_worker.py'),
                '--arm',arm,'--run-id',run_id,'--approval',str(approval.resolve())],cwd=WORKSPACE,stdout=out,stderr=err)
            while process.poll() is None:
                state=progress(root,p['arms'])
                write_status(root,dict(status='running',active_arm=arm,controller_pid=os.getpid(),worker_pid=process.pid,
                    updated_utc=now(),total_completed=sum(s['completed_sessions'] for s in state.values()),
                    total_planned=1400,by_arm=state,scoring_started=False,holdout_started=False))
                time.sleep(10)
        if process.returncode:
            state=progress(root,p['arms'])
            write_status(root,dict(status='stopped_error',active_arm=arm,exit_code=process.returncode,updated_utc=now(),
                total_completed=sum(s['completed_sessions'] for s in state.values()),total_planned=1400,by_arm=state,
                scoring_started=False,holdout_started=False))
            save(root/'controller_stop.json',dict(arm=arm,exit_code=process.returncode,stopped_utc=now(),automatic_retry=False))
            raise SystemExit(process.returncode)
    state=progress(root,p['arms'])
    save(root/'completed.json',dict(status='generation_complete_unscored',sessions=1400,completed_utc=now(),
        protocol_sha256=sha(protocol),by_arm=state,
        arm_completion_hashes={arm:sha(root/arm/'completed.json') for arm in p['arms']},scoring_started=False,holdout_started=False))
    write_status(root,dict(status='generation_complete_unscored',updated_utc=now(),total_completed=1400,total_planned=1400,
        by_arm=state,scoring_started=False,holdout_started=False))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['prepare','run'])
    parser.add_argument('--run-id',required=True);parser.add_argument('--approval',type=Path)
    args=parser.parse_args()
    if args.action=='prepare':print(verify_and_authorize(args.run_id))
    else:run(args.run_id,args.approval)
