"""冻结完整候选与强无图控制，按相同开发输入和重复交错执行。"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
import fcntl
import json
import os
from pathlib import Path
import random
import shutil
import time

import candidate_qa as candidate
import navigation_qa as qa
import graphify_qa as base
import leaderboard_audit as audit

GROUPS={'strong_no_graph':['retrieval_first'],'full_candidate':['retrieval_first']}


def prepare(parent,index,graph,output):
    if output.exists():raise FileExistsError('preserve candidate evaluation')
    prior=audit.verify(parent);base.verify_runtime(prior)
    hybrid=qa.read(index/'manifest.json');g=qa.read(graph)
    if hybrid['corpus_id']!=prior['corpus_id'] or g['corpus_id']!=prior['corpus_id'] or not g['coverage']['semantic_complete']:
        raise ValueError('candidate construction/corpus gate failed')
    for name,h in hybrid['files'].items():
        if qa.digest((index/name).read_bytes())!=h:raise ValueError('hybrid artifact changed')
    output.mkdir(parents=True)
    shutil.copytree(index,output/'hybrid')
    shutil.copy2(graph,output/'candidate-graph.json')
    for p in Path(__file__).parent.glob('*.py'):shutil.copy2(p,output/p.name)
    original=qa.read(parent/'control/protocol.json')
    for group,methods in GROUPS.items():
        arm=output/group;arm.mkdir()
        for name,expected in original['files'].items():
            src=parent/'control'/name
            if qa.digest(src.read_bytes())!=expected:raise ValueError('common source changed')
            dst=arm/name;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dst)
        arm_protocol={k:v for k,v in original.items() if k not in ['files','prompts','graph_baseline','graph_query','arm','methods']}
        arm_protocol.update(arm=group,methods=methods,prompts={m:candidate.prompt(candidate.DEFAULTS) for m in methods},
             strategy='six exploration decisions plus claim plan and semantic check; at most nine API calls and 8000 generated tokens including final',
             graph_loaded=group=='full_candidate',options=candidate.DEFAULTS,
             graph_query='shared BM25/exact/E5 RRF retrieval; complete candidate additionally uses constrained graph paths and atomic evidence groups')
        arm_protocol['files']={p.relative_to(arm).as_posix():qa.digest(p.read_bytes()) for p in arm.rglob('*') if p.is_file()}
        qa.write(arm/'protocol.json',arm_protocol)
    # Common question location keeps the audit and blind packet format compatible.
    (output/'control').mkdir();shutil.copy2(parent/'control/questions.json',output/'control/questions.json')
    shutil.copytree(parent/'control/evaluation_only',output/'control/evaluation_only')
    frozen={p.relative_to(output).as_posix():qa.digest(p.read_bytes()) for p in sorted(output.rglob('*')) if p.is_file()}
    qa.write(output/'protocol.json',{'schema':'candidate-unified-evaluation-v1','files':frozen,'groups':GROUPS,
         'replicates':3,'model':qa.MODEL,'corpus_id':prior['corpus_id'],'runtime_identity':base.runtime_identity(),
         'parent_run':str(parent),'parent_protocol_sha256':qa.digest((parent/'protocol.json').read_bytes()),
         'dataset_manifest_sha256':original['dataset_manifest_sha256'],'shuffle_seed':20260910,'planned_sessions':216,
         'limits':qa.LIMITS,'max_generated_tokens':8000,'max_model_calls':9,
         'shared_controls':'same questions, gold, corpus, DeepSeek model, numbering, tool-character and total output budgets; stronger no-graph shares hybrid retrieval, gaps and pre-answer validation',
         'whole_system_comparison':'baseline eight-exploration policy differs from the complete candidate six-exploration/two-check policy; no component-causality claim from main leaderboard',
         'first_policy':'prompted retrieval first; no hidden automatic retrieval',
         'failure_policy':'same identical-request retry cap; four consecutive no-HTTP network errors stop the process with exit code 75 before downstream scoring',
         'holdout_unlocked':False,'options':candidate.DEFAULTS})
    audit.verify(output)
    print(qa.wire({'prepared':str(output),'sessions':216}))


def run_logged(engine,q,m,key,rep,replay):
    folder=engine.run/'sessions'/f"{q['id']}--{m}--r{rep}"
    journal=folder/'invocations'/f'{time.time_ns()}.json';begin=time.monotonic()
    record={'status':'running','replay':replay,'started_unix_ns':time.time_ns(),'elapsed_seconds':None}
    qa.write(journal,record)
    try:
        result=candidate.run_one(engine,q,m,key,rep,replay);record['status']=result['status'];return result
    except BaseException:
        record['status']='error';raise
    finally:
        record['elapsed_seconds']=time.monotonic()-begin;qa.write(journal,record)


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('command',choices=['prepare','verify','smoke','run','replay'])
    cli.add_argument('--run',type=Path,required=True);cli.add_argument('--parent',type=Path)
    cli.add_argument('--index',type=Path);cli.add_argument('--graph',type=Path)
    cli.add_argument('--key-file',type=Path);cli.add_argument('--workers',type=int,default=4)
    cli.add_argument('--baseline-report',type=Path)
    a=cli.parse_args();root=a.run.resolve()
    if a.command=='prepare':prepare(a.parent.resolve(),a.index.resolve(),a.graph.resolve(),root);return
    protocol=audit.verify(root);base.verify_runtime(protocol)
    if a.command=='verify':print('PASS: candidate evaluation identity');return
    if Path(__file__).resolve()!=root/'candidate_runner.py':raise ValueError('execute frozen candidate runner')
    if a.command=='run':
        # The requested order is explicit: finish the current-method board first.
        if a.baseline_report is None:raise ValueError('a completed current-method leaderboard report is required first')
        report=qa.read(a.baseline_report)
        if report.get('protocol_sha256')!=protocol['parent_protocol_sha256'] or not report.get('all_arms_rankable'):
            raise ValueError('baseline complete-grid/source-review gate not met')
    base.SECRET=a.key_file.read_text().strip() if a.key_file else ''
    base.reset_transport_circuit()
    qa.write=base.save;qa.instrument_file_reads()
    with (root/'runtime.lock').open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        engines={group:candidate.Engine(root/group,group,root/'hybrid',root/'candidate-graph.json' if group=='full_candidate' else None,protocol['options']) for group in protocol['groups']}
        if a.command=='smoke':
            checks=[]
            for group,e in engines.items():
                s=candidate.Session(e,'retrieval_first','movingCone dynamicMeshDict mesh motion')
                result,accounting=s.dispatch({'action':'locate','needs':['mesh configuration']},6000)
                if result.get('status')!='ok' or not s.seen:raise ValueError('candidate evidence smoke failed')
                checks.append({'group':group,'result':result,'accounting':accounting})
            qa.write(root/'verification/adapter-smoke.json',checks);print('PASS: candidate/strong-no-graph tools, zero model calls');return
        questions=qa.read(root/'control/questions.json')
        jobs=[(group,q,m,rep) for q in questions for rep in range(1,4) for group,methods in protocol['groups'].items() for m in methods]
        random.Random(protocol['shuffle_seed']).shuffle(jobs)
        journal=root/'invocations'/f'{time.time_ns()}.json';begin=time.monotonic()
        state={'pid':os.getpid(),'state':'running','jobs':len(jobs),'completed':0,'errors':[],'command':a.command}
        qa.write(journal,state)
        with ThreadPoolExecutor(max_workers=a.workers) as pool:
            futures={}
            for group,q,m,rep in jobs:
                name=f"{q['id']}--{m}--r{rep}"
                if a.command=='run' and (root/group/'sessions'/name/'result.json').exists():state['completed']+=1;continue
                futures[pool.submit(run_logged,engines[group],q,m,base.SECRET or None,rep,a.command=='replay')]=group+'/'+name
            for f in as_completed(futures):
                try:r=f.result();state['completed']+=1;print('DONE',futures[f],r['status'],flush=True)
                except Exception as e:
                    state['errors'].append({'session':futures[f],'type':type(e).__name__});print('ERROR',futures[f],type(e).__name__,flush=True)
                qa.write(journal,{**state,'elapsed_seconds':time.monotonic()-begin})
        outage=any(error['type']=='GlobalTransportOutage' for error in state['errors'])
        qa.write(journal,{**state,'state':'network_circuit_open' if outage else 'finished','elapsed_seconds':time.monotonic()-begin})
        audit.verify(root)
        if outage:raise SystemExit(75)


if __name__=='__main__':main()
