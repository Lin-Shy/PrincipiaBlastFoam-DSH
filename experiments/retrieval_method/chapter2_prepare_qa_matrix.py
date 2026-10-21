"""Prepare all ten dev arms from one runtime; run selected exact models."""
import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
import json
import os
from pathlib import Path
import subprocess
import sys
from chapter2_autonomous_qa import read,save,sha,PROJECT

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('dataset','sampling','corpus','manifest','source-map','models','e5-index','graphs','proxy-settings','output','python'):
        p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--hf-cache',type=Path,required=True);p.add_argument('--prepare-only',action='store_true')
    p.add_argument('--run-model',action='append',choices=['qwen3-8b','qwen3-14b']);p.add_argument('--workers',type=int,default=2)
    a=p.parse_args();seal=read(a.dataset/'dataset-seal.json');sampling=read(a.sampling)
    if sampling['dataset_id']!=seal['dataset_id']:raise ValueError('sampling dataset identity differs')
    qpath=a.dataset/'model/questions.json'
    if sha(qpath)!=seal['files']['model/questions.json']:raise ValueError('sealed production questions drift')
    ids=sampling['subsets']['development_pilot']['ids'];arms=[]
    runner=PROJECT/'experiments/retrieval_method/chapter2_autonomous_qa.py'
    for model in ('qwen3-8b','qwen3-14b'):
        for method in ('bm25','e5','hybrid','graph','none'):
            name=model+'_'+method;folder=a.output/'arms'/name
            cmd=[str(a.python.resolve()),str(runner),'--questions',str(qpath.resolve()),'--model',model,'--method',method,
              '--tokenizer',str((a.models/model).resolve()),'--proxy-settings',str(a.proxy_settings.resolve()),'--output',str(folder.resolve())]
            for qid in ids:cmd+=['--question-id',qid]
            if method!='none':cmd+=['--corpus',str(a.corpus.resolve()),'--corpus-manifest',str(a.manifest.resolve()),'--source-map',str(a.source_map.resolve())]
            if method in {'e5','hybrid'}:cmd+=['--e5-index',str(a.e5_index.resolve())]
            if method=='graph':cmd+=['--graph',str((a.graphs/'full.json').resolve())]
            folder.mkdir(parents=True,exist_ok=True)
            with (folder/'prepare.log').open('w',encoding='utf-8') as logfile:
                finished=subprocess.run(cmd+['--prepare-only'],stdout=logfile,stderr=subprocess.STDOUT)
            if finished.returncode:raise RuntimeError('arm preparation failed: '+name)
            frozen_cmd=list(cmd);frozen_cmd[1]=str((folder/'runtime/experiments/retrieval_method/chapter2_autonomous_qa.py').resolve())
            protocol=read(folder/'protocol.json');arms.append({'name':name,'model':model,'method':method,'command':frozen_cmd,
              'protocol_sha256':sha(folder/'protocol.json'),'runtime_source_sha256':protocol['source_sha256']})
    common=arms[0]['runtime_source_sha256']
    if any(arm['runtime_source_sha256']!=common for arm in arms):raise ValueError('ten arm runtime snapshots differ')
    binding={'schema':'ten_arm_development_matrix_v1','formal_result':False,'question_ids':ids,
      'dataset_id':seal['dataset_id'],'sampling_sha256':sha(a.sampling),'arms':arms,'runtime_identical':True,
      'execution_policy':'Run each prepared immutable runtime snapshot; never call the live application source during an arm.',
      'orchestrator_sha256':sha(Path(__file__))}
    manifest=a.output/'matrix.json'
    if manifest.exists() and read(manifest)!=binding:raise ValueError('matrix drift; create a new development revision')
    save(manifest,binding)
    target=a.output/'orchestrator-runtime'/Path(__file__).name
    target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(Path(__file__).read_bytes())
    if a.prepare_only:print(json.dumps({'prepared_arms':10,'questions_per_arm':len(ids),'runtime_identical':True}));return
    selected=[arm for arm in arms if not a.run_model or arm['model'] in a.run_model]
    def run(arm):
        folder=a.output/'arms'/arm['name'];env=dict(os.environ);env['HF_HUB_CACHE']=str(a.hf_cache.resolve());env['PYTHONIOENCODING']='utf-8'
        with (folder/'execution.log').open('a',encoding='utf-8') as logfile:
            finished=subprocess.run(arm['command'],env=env,stdout=logfile,stderr=subprocess.STDOUT)
        summary=read(folder/'summary.json') if (folder/'summary.json').exists() else {}
        result={'arm':arm['name'],'returncode':finished.returncode,'completed_sessions':len(summary.get('sessions',[])),
          'unattempted_sessions':summary.get('unattempted_sessions',len(ids)),
          'transport_circuit_open':summary.get('transport_circuit_open'),'formal_result':False}
        save(folder/'launch-receipt.json',result);return result
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        jobs=[pool.submit(run,arm) for arm in selected]
        for job in as_completed(jobs):print(json.dumps(job.result()),flush=True)

if __name__=='__main__':main()
