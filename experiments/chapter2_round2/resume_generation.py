"""Explicit local serialization repair; retain first exposure and never resend.

Original controller/worker and original receipts stay unchanged. Canonical new
view copies closed receipts byte for byte; only never-started sessions call API.
"""
import argparse
from collections import Counter
from datetime import datetime,timezone
import os
import random
import shutil
import subprocess
import time

from common import *

OLD='answer14b_001'
NEW='answer14b_002'

def safe_save(path,value):
    """Escape Unicode in the on-disk JSON container without editing strings."""
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf-8')as f:f.write(json.dumps(value,ensure_ascii=True,indent=2,allow_nan=False)+'\n')

def verify():
    from e2e import approval_check
    p=approval_check(ARCHIVE/'authorizations/answer14b_001_generation.json',ARCHIVE/'configs/e2e_14b_v1.json')
    for n,h in p['code'].items():
        if sha(HERE/n)!=h:raise ValueError('frozen generation source drift')
    for n,h in p['legacy_code'].items():
        if sha(PROJECT/n)!=h:raise ValueError('legacy source drift')
    return p

def prepare():
    p=verify();old=ARCHIVE/'e2e_runs'/OLD;new=ARCHIVE/'e2e_runs'/NEW
    new.mkdir(exist_ok=False);bindings={};broken=[]
    for arm in p['arms']:
        for folder in (old/arm/'generation').glob('*'):
            if not folder.is_dir():continue
            source=folder/'result.json'
            if not source.exists():raise ValueError('unresolved request folder requires explicit diagnosis')
            try:read(source)
            except json.JSONDecodeError:
                if source.stat().st_size!=0:raise ValueError('unexpected nonempty invalid receipt')
                broken.append(dict(arm=arm,id=folder.name,original_empty_result_sha256=sha(source)))
            target=new/arm/'generation'/folder.name
            shutil.copytree(folder,target,ignore=(lambda d,n:['result.json']if Path(d)==folder and source.stat().st_size==0 else []))
            for path in folder.rglob('*'):
                if path.is_file()and path.stat().st_size:
                    copied=target/path.relative_to(folder)
                    if sha(copied)!=sha(path):raise ValueError('copy drift')
                    bindings[path.relative_to(old).as_posix()]=sha(path)
    if broken!=[dict(arm='graph',id='E20-03',original_empty_result_sha256=sha(old/'graph/generation/E20-03/result.json'))]:
        raise ValueError('unexpected interruption identity')
    save(new/'continuation_protocol.json',dict(schema='round2_local_delivery_continuation_v1',original_run=OLD,run_id=NEW,
        original_generation_protocol_sha256=sha(ARCHIVE/'configs/e2e_14b_v1.json'),original_approval_sha256=sha(ARCHIVE/'authorizations/answer14b_001_generation.json'),
        created_utc=datetime.now(timezone.utc).isoformat(),user_instruction='继续，完成付费评分，完成新留出集验证，确认',
        completed_reused=123,local_delivery_failures=1,never_started_sessions=1276,total_sessions=1400,
        original_copied_file_sha256=bindings,broken=broken,code_sha256=sha(Path(__file__)),
        amendment='On-disk JSON ensure_ascii=True only. Interrupted E20-03 reconstructed exclusively from recorded replies; retains local serialization failure0, no paid replay. Same model-facing prompts/tools/budgets/rankers. First-exposure status retained.',
        monitor_repair='Only count valid closed result JSON; observer cannot terminate generation on an unfinished write.',
        paid_judging='Not part of this generator; use separate frozen scoring authorization.'))
    print('Continuation prepared;123 copied,1 local failure to close offline,1276 never-started sessions; no API calls')

def run_session(folder,q,arm,p,engine,counter,corpus,replay=False):
    from retrieval import SlotsBackend
    from principia_core.retrieval.knowledge_agent import AutonomousKnowledgeAgent,ModelBudget
    from principia_core.retrieval.knowledge_qa import KnowledgeToolSession,KnowledgeBudget
    from chapter2_common_qa_interface import NeutralToolClient
    from chapter2_qa_deployment import DeploymentResponse,ANSWER_CHECKLIST
    from chapter2_qwen_routing import routed_client
    class Backend:
        calls=0
        def search(self,query,limit):
            rows,trace=engine.query(query)
            path=folder/'retrieval_traces'/f'{self.calls:02d}.json';self.calls+=1
            if replay:
                if read(path)!=dict(query=query,trace=trace):raise ValueError('offline retrieval replay differs')
            else:safe_save(path,dict(query=query,trace=trace))
            return SlotsBackend(rows).search(query,limit)
    tools=KnowledgeToolSession('bm25',corpus,Backend(),KnowledgeBudget(**p['knowledge_budget']))
    client=routed_client('qwen3-14b',folder/'requests',workload='bulk',timeout=180)
    if replay:
        class Replay:
            deployment=client.deployment
            def __call__(self,body,turn):
                record=read(folder/'requests'/f'{turn:02d}.json')
                if body!=record['request']:raise ValueError('offline request replay differs')
                return record
        client=Replay()
    client=DeploymentResponse(NeutralToolClient(client),'qwen3-14b',ANSWER_CHECKLIST)
    start=time.monotonic()
    result=AutonomousKnowledgeAgent('qwen3-14b',tools,client,counter,ModelBudget(**p['model_budget'])).run(q['question'])
    result.update(id=q['id'],arm=arm,answer_model='qwen3-14b',protocol_sha256=sha(ARCHIVE/'configs/e2e_14b_v1.json'),
        seconds=time.monotonic()-start,delivered_lines=[dict(path=x,line=n)for x,n in sorted(tools.delivered_lines)])
    return result

def worker(arm,offline=False):
    p=verify();new=ARCHIVE/'e2e_runs'/NEW
    if sha(Path(__file__))!=read(new/'continuation_protocol.json')['code_sha256']:raise ValueError('continuation source drift')
    from chapter2_knowledge_input_guard import install
    install(QUESTIONS)
    from retrieval import GraphEngine,TextEngine
    from chapter2_autonomous_qa import load_tokenizer
    from chapter2_common_qa_interface import neutral_messages
    from chapter2_qa_deployment import token_counter,ANSWER_CHECKLIST
    from principia_core.retrieval.knowledge_qa import FrozenKnowledgeCorpus
    from launch_worker import stopping_reason
    root=new/arm;root.mkdir(parents=True,exist_ok=True)
    engine=GraphEngine(arm)if arm in ['graph','no_traversal','anchor_only']else TextEngine(arm)
    raw,_=load_tokenizer(RESOURCES/'tokenizers/qwen3-14b','qwen3-14b')
    counter=token_counter(lambda messages:raw(neutral_messages(messages)),'bulk',ANSWER_CHECKLIST)
    corpus=FrozenKnowledgeCorpus(RESOURCES/'corpus',RESOURCES/'corpus-manifest.json')
    qs=public_questions();random.Random(20261020).shuffle(qs);streak=0
    for q in qs:
        folder=root/'generation'/q['id']
        if (folder/'result.json').exists():continue
        replay=arm=='graph'and q['id']=='E20-03'
        if offline and not replay:continue
        if folder.exists()and not replay:raise ValueError('existing unclosed request requires audit, never resend')
        folder.mkdir(parents=True,exist_ok=replay)
        result=run_session(folder,q,arm,p,engine,counter,corpus,replay)
        if replay:
            safe_save(folder/'recovered_result.json',result)
            result={**result,'status':'local_result_serialization_failure','answer':None,'references':None,'references_delivered':False,
                'original_reconstructed_status':result['status'],'local_closure':'Recorded API replies replayed offline; no paid requests; not a delivered valid final answer in original execution',
                'seconds':sum(t['response'].get('seconds',0)for t in result['turns'])}
        safe_save(folder/'result.json',result)
        streak=streak+1 if result['status']in {'transport_error','http_rejected','invalid_response'}else 0
        reason=stopping_reason(result,streak)
        if reason:
            safe_save(root/'infrastructure_stop.json',dict(reason=reason,id=q['id'],no_retry=True));raise RuntimeError(reason)
    if not offline:
        counts=Counter(read(root/'generation'/q['id']/'result.json')['status']for q in qs)
        safe_save(root/'completed.json',dict(arm=arm,questions=200,statuses=dict(counts),protocol_sha256=sha(ARCHIVE/'configs/e2e_14b_v1.json'),
            continuation_protocol_sha256=sha(new/'continuation_protocol.json'),results_sha256={q['id']:sha(root/'generation'/q['id']/'result.json')for q in qs}))

def controller():
    from score_round2 import update
    p=verify();new=ARCHIVE/'e2e_runs'/NEW;logs=new/'logs';logs.mkdir(exist_ok=False)
    for arm in p['arms']:
        with (logs/(arm+'.stdout.log')).open('x',encoding='utf-8')as out,(logs/(arm+'.stderr.log')).open('x',encoding='utf-8')as err:
            process=subprocess.Popen([sys.executable,'-X','utf8','-u',str(Path(__file__)),'worker','--arm',arm],cwd=WORKSPACE,stdout=out,stderr=err)
            while process.poll()is None:
                state={}
                for method in p['arms']:
                    rows=[]
                    for file in (new/method/'generation').glob('*/result.json'):
                        try:rows.append(read(file))
                        except json.JSONDecodeError:continue
                    state[method]=dict(completed_sessions=len(rows),statuses=dict(Counter(r['status']for r in rows)))
                update(new/'live_status.json',dict(status='running',active_arm=arm,controller_pid=os.getpid(),worker_pid=process.pid,
                    total_completed=sum(s['completed_sessions']for s in state.values()),total_planned=1400,by_arm=state,
                    continuation_of=OLD,updated_utc=datetime.now(timezone.utc).isoformat()))
                time.sleep(10)
        if process.returncode:
            safe_save(new/'controller_stop.json',dict(arm=arm,exit_code=process.returncode,no_retry=True));raise SystemExit(process.returncode)
    safe_save(new/'completed.json',dict(status='generation_complete_unscored',sessions=1400,continuation_of=OLD,
        original_results_unchanged=True,completion_hashes={arm:sha(new/arm/'completed.json')for arm in p['arms']}))
    update(new/'live_status.json',dict(status='generation_complete_unscored',total_completed=1400,total_planned=1400))

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('action',choices=['prepare','offline-close','worker','run']);ap.add_argument('--arm')
    a=ap.parse_args()
    if a.action=='prepare':prepare()
    elif a.action=='offline-close':worker('graph',True)
    elif a.action=='worker':worker(a.arm)
    else:controller()
