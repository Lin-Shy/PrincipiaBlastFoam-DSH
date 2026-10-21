"""Paired development ablations from the same frozen ten-arm QA implementation."""
import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
import hashlib
import json
import os
from pathlib import Path
import subprocess

def read(p):return json.loads(p.read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,v):
    p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def replace(command,name,value):
    c=list(command)
    if name in c:c[c.index(name)+1]=str(value)
    else:c.extend([name,str(value)])
    return c

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--matrix',type=Path,required=True)
    p.add_argument('--variants',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--run-model',action='append',choices=['qwen3-8b','qwen3-14b'],default=[])
    p.add_argument('--workers',type=int,default=2);a=p.parse_args()
    if a.output.exists():raise FileExistsError('new ablation development revision required')
    if not 1<=a.workers<=2:raise ValueError('development worker budget is 1 or 2')
    matrix=read(a.matrix);arms=[];common=None;env=dict(os.environ);env['PYTHONIOENCODING']='utf-8'
    for model in ('qwen3-8b','qwen3-14b'):
        base=next(r for r in matrix['arms'] if r['model']==model and r['method']=='graph')
        base_folder=Path(base['command'][base['command'].index('--output')+1])
        if sha(base_folder/'protocol.json')!=base['protocol_sha256']:raise ValueError('full-graph baseline protocol drift')
        base_protocol=read(base_folder/'protocol.json')
        original_runtime=base['runtime_source_sha256'];runtime_root=Path(base['command'][1]).parents[2]
        for name,h in original_runtime.items():
            if sha(runtime_root/name)!=h:raise ValueError('frozen baseline source drift')
        for variant in ('no_cross','no_conditions','no_extension'):
            name=model+'_graph_'+variant;folder=a.output.resolve()/'arms'/name
            command=replace(base['command'],'--output',folder)
            command=replace(command,'--graph',a.variants.resolve()/(variant+'.json'))
            command=replace(command,'--graph-ablation',variant)
            prepared=subprocess.run(command+['--prepare-only'],capture_output=True,text=True,encoding='utf-8',env=env)
            if prepared.returncode:raise RuntimeError(prepared.stderr)
            protocol=read(folder/'protocol.json')
            if protocol['source_sha256']!=original_runtime:raise ValueError('ablation runtime differs from full-graph pilot')
            if common is not None and common!=protocol['source_sha256']:raise ValueError('ablation arms differ in common implementation')
            common=protocol['source_sha256']
            if protocol['selected_ids']!=base_protocol['selected_ids'] or set(protocol['selected_ids'])!=set(matrix['question_ids']):
                raise ValueError('development selection drift')
            command[1]=str(folder/'runtime/experiments/retrieval_method/chapter2_autonomous_qa.py')
            arms.append({'name':name,'model':model,'variant':variant,'command':command,
              'protocol_sha256':sha(folder/'protocol.json'),'graph_sha256':sha(a.variants/(variant+'.json'))})
    record={'schema':'paired_frozen_development_ablation_pilot_v1','formal_result':False,'matrix_sha256':sha(a.matrix),
      'question_ids':matrix['question_ids'],'common_runtime_source_sha256':common,'arms':arms,
      'run_models':a.run_model,'workers':a.workers,'full_graph_baseline':'Existing same-model graph arm in the bound development matrix; no baseline quality resampling.',
      'implementation_sha256':sha(Path(__file__))}
    save(a.output/'matrix.json',record)
    runtime=a.output/'orchestrator_runtime'/Path(__file__).name;runtime.parent.mkdir(parents=True,exist_ok=True);runtime.write_bytes(Path(__file__).read_bytes())
    def run(arm):
        folder=a.output/'arms'/arm['name'];log=folder/'execution.txt'
        with log.open('w',encoding='utf-8') as stream:
            r=subprocess.run(arm['command'],stdout=stream,stderr=subprocess.STDOUT,env=env)
        summary=read(folder/'summary.json') if (folder/'summary.json').exists() else {}
        return {'arm':arm['name'],'returncode':r.returncode,'completed_sessions':len(summary.get('sessions',[])),
          'unattempted_sessions':summary.get('unattempted_sessions'),'transport_circuit_open':summary.get('transport_circuit_open'),
          'execution_sha256':sha(log),'formal_result':False}
    completed=[]
    with ThreadPoolExecutor(max_workers=a.workers) as executor:
        futures=[executor.submit(run,arm) for arm in arms if arm['model'] in a.run_model]
        for future in as_completed(futures):
            row=future.result();completed.append(row);print(json.dumps(row),flush=True)
    save(a.output/'execution-summary.json',{'formal_result':False,'completed_arms':completed,
      'prepared_arms':len(arms),'models_not_run':sorted({'qwen3-8b','qwen3-14b'}-set(a.run_model))})

if __name__=='__main__':main()
