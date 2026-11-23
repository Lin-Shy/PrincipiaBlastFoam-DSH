"""One scoped single-case scheduler bridge. No solver runs on the controller."""
import argparse,hashlib,json,os,re,shlex,subprocess,sys,tarfile,time
from pathlib import Path
HERE=Path(__file__).resolve().parent
APP=HERE.parents[1]
sys.path.insert(0,str(APP/'experiments/end2end'))
sys.path.insert(0,str(APP/'deployment/remote'))
import cluster_job
from linux_scheduler_bridge import guarded_plan
FILES=['0/U','0/p','constant/transportProperties','system/blockMeshDict','system/controlDict','system/fvSchemes','system/fvSolution','system/setFieldsDict']
def put(p,x):
 p.write_text(json.dumps(x,indent=2)+'\n')
def load(p):return json.loads(p.read_text())
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def ssh(cfg,cmd,timeout=60):
 return cluster_job.ssh(cfg,cmd,capture_output=True,text=True,timeout=timeout)
def validate(case):
 found=[]
 for p in case.rglob('*'):
  if p.is_symlink():raise ValueError('symlink input refused')
  if p.is_file():found.append(p.relative_to(case).as_posix())
 if sorted(found)!=sorted(FILES):raise ValueError('Exactly eight input dictionaries required')
 if sum((case/f).stat().st_size for f in FILES)>262144:raise ValueError('input size')
 for f in FILES:
  text=(case/f).read_text('ascii')
  if re.search(r'#\s*(code|include|calc|eval)|\b(systemCall|coded|libs|functions)\b',text):
   raise ValueError('Executable or external dictionary content refused')
 mesh=(case/'system/blockMeshDict').read_text()
 if not re.search(r'\(10\s+10\s+1\)',mesh):raise ValueError('fixed 100-cell mesh required')
 control=(case/'system/controlDict').read_text()
 for key,value in [('application','icoFoam'),('endTime','0.02'),('deltaT','0.001'),('writeInterval','20'),('writeFormat','ascii')]:
  if not re.search(r'\b'+key+r'\s+'+re.escape(value)+r'\s*;',control):raise ValueError('fixed '+key)
 if not re.search(r'\bpFinal\s*\{',(case/'system/fvSolution').read_text()):raise ValueError('Foundation 9 requires pFinal')
def main():
 p=argparse.ArgumentParser()
 p.add_argument('action',choices=['validate','submit','status','collect'])
 p.add_argument('--run',type=Path,required=True)
 a=p.parse_args();run=a.run.resolve();cfg=load(run/'scheduler.json');plan=load(run/'protocol.json')
 assert plan['simulation_jobs_max']==1 and plan['authorized_scope']=='one real-model single-case functional acceptance'
 spec=guarded_plan(cluster_job,cfg,plan['run_id'])
 state=run/'operator';state.mkdir(exist_ok=True)
 case=run/'workspace/case'
 if a.action=='validate':
  validate(case);print(json.dumps({'valid':True,'files':len(FILES)}));return
 if a.action=='submit':
  validate(case)
  intent=state/'submit_intent.json'
  with intent.open('x') as f:json.dump({'run_id':plan['run_id'],'remote':spec['remote'],'unix':time.time()},f)
  payload=state/'payload';(payload/'case').mkdir(parents=True)
  hashes={}
  for name in FILES:
   target=payload/'case'/name;target.parent.mkdir(exist_ok=True,parents=True)
   target.write_bytes((case/name).read_bytes());hashes[name]=digest(target)
  put(state/'registered_inputs.json',hashes)
  (payload/'node_summary.py').write_bytes((HERE/'node_summary.py').read_bytes())
  script="""set -euo pipefail
cp -r payload/case case
blockMesh -case case > logs/blockMesh.log 2>&1
checkMesh -case case > logs/checkMesh.log 2>&1
setFields -case case > logs/setFields.log 2>&1
/XYFS01/sysu_pww_2/software/OpenFOAM-9/platforms/linux64GccDPInt32Opt/bin/icoFoam -case case > logs/icoFoam.log 2>&1
/usr/bin/python3 payload/node_summary.py
"""
  (payload/'run_case.sh').write_text(script)
  batch=spec['batch_script'].replace('node=$(hostname -s)','printf "%s\\n" "$record" > logs/scheduler-allocation.txt\nnode=$(hostname -s)')
  batch=batch.replace('bash payload/run_case.sh','ulimit -f 204800\nbash payload/run_case.sh')
  (state/'batch.sh').write_text(batch)
  archive=state/'payload.tar'
  with tarfile.open(archive,'x') as tar:
   for item in sorted(payload.rglob('*')):
    if item.is_file():tar.add(item,arcname='payload/'+item.relative_to(payload).as_posix(),recursive=False)
  remote=spec['remote'];q=shlex.quote(remote)
  # mkdir is exclusive; an ambiguous outcome must be reconciled, never resubmitted.
  ssh(cfg,'umask 077; test "$(id -u)" = 15505 && mkdir '+q+' && mkdir '+q+'/logs '+q+'/tmp '+q+'/home')
  subprocess.run(['scp','-q','-F',cfg['ssh_config'],str(archive),str(state/'batch.sh'),cfg['ssh_target']+':'+remote+'/'],check=True,timeout=120)
  result=ssh(cfg,'cd '+q+' && sha256sum payload.tar')
  assert result.stdout.split()[0]==digest(archive)
  ssh(cfg,'cd '+q+' && tar -xf payload.tar')
  result=ssh(cfg,shlex.join(spec['submit_argv']))
  (state/'submit.stdout').write_text(result.stdout)
  m=re.search(r'Submitted batch job\s+(\d+)',result.stdout)
  if not m:raise RuntimeError('Unknown submission; do not retry')
  receipt={'job_id':m[1],'run_id':plan['run_id'],'remote':remote,'input_sha256':hashes}
  put(state/'job_receipt.json',receipt);print(json.dumps(receipt));return
 receipt=load(state/'job_receipt.json');assert receipt['run_id']==plan['run_id'] and receipt['remote']==spec['remote']
 job=receipt['job_id'];assert job.isdigit()
 if a.action=='status':
  result=ssh(cfg,'sacct -j '+job+' -n -P --format=JobID,JobName,State,ExitCode,NodeList,Elapsed,AllocCPUS')
  out={'job_id':job,'remote':receipt['remote'],'accounting':result.stdout[:16384]}
  put(state/'latest_status.json',out);print(json.dumps(out));return
 # Read only bounded control evidence, never pull native field directories.
 allowed=['summary.json','logs/scheduler-allocation.txt','logs/allocated_job_id.txt','logs/allocated_host.txt','logs/pipeline.exit','logs/icoFoam.log','logs/checkMesh.log','logs/blockMesh.log','logs/setFields.log','logs/pipeline.stderr']
 remote=receipt['remote']
 result={}
 for name in allowed:
  cmd='p='+shlex.quote(remote+'/'+name)+'; if test -f "$p"; then if test "$(wc -c < "$p")" -le 65536; then cat "$p"; else tail -c 65536 "$p"; fi; fi'
  raw=ssh(cfg,cmd).stdout
  dest=run/'workspace/evidence'/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_text(raw)
  result[name]={'bytes':len(raw.encode()),'sha256':digest(dest)}
 put(run/'workspace/evidence/receipt.json',receipt)
 print(json.dumps({'job_id':job,'remote_results':remote+'/case','bounded_evidence':'evidence/','files':result}))
if __name__=='__main__':main()
