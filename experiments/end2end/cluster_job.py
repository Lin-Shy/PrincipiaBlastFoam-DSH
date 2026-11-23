"""Common Chapter 3 scheduler bridge for BOTH arms; no implicit authorization.

Plan is offline. Live actions require an operator-owned binding and scoped grant.
Path checks protect against mistakes, not same-UID arbitrary code. No cancel API.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import tarfile

REMOTE_ROOT='/XYFS02/HDD_POOL/sysu_pww/sysu_pww_2/dsh-simulation/runs'

def load(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def write(p,obj):
    with p.open('x',encoding='utf-8') as f:json.dump(obj,f,indent=2)
def digest(p):
    result=hashlib.sha256()
    with p.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):result.update(block)
    return result.hexdigest()

def plan(config,run_id):
    if not re.fullmatch(r'c3-[a-z0-9][a-z0-9-]{0,55}',run_id):raise ValueError('invalid chapter-owned run id')
    for key in ['partition','tasks','wall_minutes','memory_mib']:
        if config.get(key) is None:raise ValueError('unbound resource/runtime: '+key)
    if any(not isinstance(config[k],int) or config[k]<=0 for k in ['tasks','wall_minutes','memory_mib']):raise ValueError('positive resource bounds required')
    if not re.fullmatch(r'[a-zA-Z0-9_-]+',config['partition']):raise ValueError('invalid partition')
    if config.get('runtime_environment'):
        environment=config['runtime_environment']; hashes=config.get('runtime_sha256',{})
        if not hashes:raise ValueError('runtime hashes required')
        lines=['unset LD_PRELOAD LD_LIBRARY_PATH BASH_ENV ENV PYTHONPATH']
        for path,checksum in hashes.items():
            if not path.startswith('/') or not re.fullmatch(r'[0-9a-f]{64}',checksum):raise ValueError('invalid runtime hash binding')
            lines.append('test "$(sha256sum '+shlex.quote(path)+' | cut -d \" \" -f1)" = '+shlex.quote(checksum))
        for key,value in environment.items():
            if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*',key) or key in ['HOME','TMPDIR']:raise ValueError('invalid runtime environment key')
            lines.append('export '+key+'='+shlex.quote(str(value)))
        runtime_setup='\n'.join(lines)
    else:
        for k in ['openfoam_bashrc','blastfoam_bashrc']:
            if not str(config.get(k,'')).startswith('/') or '\n' in config[k]:raise ValueError('absolute runtime binding required')
        runtime_setup='source '+shlex.quote(config['openfoam_bashrc'])+'\nsource '+shlex.quote(config['blastfoam_bashrc'])
    remote=f'{REMOTE_ROOT}/{run_id}'
    script=f'''#!/bin/bash
set -euo pipefail
unset LD_LIBRARY_PATH LD_PRELOAD BASH_ENV ENV PYTHONPATH
export PATH=/usr/bin:/bin
test -n "${{SLURM_JOB_ID:-}}" && test -n "${{SLURM_JOB_NODELIST:-}}"
scontrol show job "$SLURM_JOB_ID" >/dev/null
node=$(hostname -s)
scontrol show hostnames "$SLURM_JOB_NODELIST" | sed 's/\\..*//' | grep -Fx "$node" >/dev/null
test "$(pwd -P)" = {shlex.quote(remote)}
export HOME="$PWD/home" TMPDIR="$PWD/tmp"
mkdir -p "$HOME" "$TMPDIR" logs
{runtime_setup}
printf '%s\\n' "$SLURM_JOB_ID" > logs/allocated_job_id.txt
hostname > logs/allocated_host.txt
# run_case.sh includes mesh, initialization, solver and computational postprocessing.
# Files stay on disk; the model connection does not own solver lifetime.
set +e
bash payload/run_case.sh > logs/pipeline.stdout 2> logs/pipeline.stderr
code=$?
printf '%s\\n' "$code" > logs/pipeline.exit
exit "$code"
'''
    command=['yhbatch','-N','1','-n',str(config['tasks']),'-p',config['partition'],
             '--time',str(config['wall_minutes']),'--mem',str(config['memory_mib']),
             '--job-name',run_id,'--chdir',remote,'--output',remote+'/logs/%j.out',
             '--error',remote+'/logs/%j.err',remote+'/batch.sh']
    command[1:1]=['--no-requeue','--export=NONE'] + (['--exclusive'] if config.get('exclusive') else [])
    return {'run_id':run_id,'remote':remote,'submit_argv':command,'batch_script':script,
            'validation':'scheduler flags/MPI/environment still require real common acceptance'}

def authorize(config,grant,run_id,action):
    if not grant.get('live_actions_allowed') or run_id not in grant.get('run_ids',[]):raise PermissionError('No scoped live grant for this run')
    if action not in grant.get('actions',[]):raise PermissionError('Action not authorized')
    if not config.get('ssh_config') or not config.get('ssh_target'):raise ValueError('SSH binding missing')
    for key in ['tasks','wall_minutes','memory_mib']:
        if config[key]>grant.get('limits',{}).get(key,0):raise PermissionError('Resource grant missing/exceeded: '+key)
    # A grant is an operator workflow input, not proof of OS isolation or new budget.

def ssh(config,command,**kwargs):
    timeout=kwargs.pop('timeout',60)
    return subprocess.run(['ssh','-F',config['ssh_config'],config['ssh_target'],'env -u LD_LIBRARY_PATH -u LD_PRELOAD bash --noprofile --norc -c '+shlex.quote(command)],check=True,timeout=timeout,**kwargs)

def run(action,config,run_id,state,payload=None,grant=None):
    spec=plan(config,run_id)
    if action=='plan':return spec
    authorize(config,grant or {},run_id,action)
    state=Path(state);state.mkdir(parents=True,exist_ok=True)
    if action=='stage':
        if not payload:raise ValueError('payload directory required')
        original=Path(payload)
        if original.is_symlink() or getattr(original.lstat(),'st_file_attributes',0)&1024:
            raise ValueError('reparse input refused')
        root=original.resolve()
        if not (root/'run_case.sh').is_file():raise ValueError('run_case.sh required')
        paths=sorted(root.rglob('*'))
        if root.is_symlink() or any(p.is_symlink() or getattr(p.lstat(),'st_file_attributes',0)&1024 for p in paths):raise ValueError('reparse input refused')
        # Exclusive record prevents accidental repeat after ambiguous network outcome.
        write(state/'stage_intent.json',spec)
        archive=state/'payload.tar'
        with tarfile.open(archive,'x') as tar:
            for p in paths:
                if p.is_file():tar.add(p,arcname='payload/'+p.relative_to(root).as_posix(),recursive=False)
        (state/'batch.sh').write_text(spec['batch_script'],encoding='utf-8',newline='\n')
        hpc=config.get('hpc_entry')
        if not hpc:raise ValueError('operator hpc.py binding required')
        subprocess.run([config.get('python','python'),hpc,'new-run',run_id,'--workspace','xyfs02'],check=True,timeout=60)
        subprocess.run(['scp','-F',config['ssh_config'],str(archive),str(state/'batch.sh'),config['ssh_target']+':'+spec['remote']+'/'],check=True,timeout=120)
        check=ssh(config,'cd '+shlex.quote(spec['remote'])+' && sha256sum payload.tar',capture_output=True,text=True)
        if check.stdout.split()[0]!=digest(archive):raise RuntimeError('Uploaded payload hash mismatch')
        ssh(config,'cd '+shlex.quote(spec['remote'])+' && tar -xf payload.tar')
        result={'run_id':run_id,'remote':spec['remote'],'payload_sha256':digest(archive)}
        write(state/'stage_receipt.json',result);return result
    if action=='submit':
        staged=load(state/'stage_receipt.json')
        if staged['run_id']!=run_id or staged['remote']!=spec['remote']:raise ValueError('stage identity mismatch')
        write(state/'submit_intent.json',spec)
        result=ssh(config,shlex.join(spec['submit_argv']),capture_output=True,text=True)
        match=re.search(r'Submitted batch job\s+(\d+)',result.stdout)
        (state/'submit.stdout').write_text(result.stdout,encoding='utf-8')
        if not match:raise RuntimeError('Unknown submit outcome: reconcile intent, never auto-retry')
        receipt={'run_id':run_id,'remote':spec['remote'],'job_id':match.group(1)}
        write(state/'job_receipt.json',receipt);return receipt
    receipt=load(state/'job_receipt.json')
    if receipt['run_id']!=run_id or receipt['remote']!=spec['remote'] or not re.fullmatch(r'\d+',receipt['job_id']):raise ValueError('job ownership mismatch')
    if action=='status':
        result=ssh(config,'scontrol show job '+receipt['job_id'],capture_output=True,text=True)
        return {'job_id':receipt['job_id'],'scheduler_text':result.stdout,'scientific_success':'not_assessed'}
    if action=='collect':
        # Archive only the run recorded in this receipt. Never extract untrusted members.
        destination=state/'collected.tar'
        if destination.exists() or (state/'collection_receipt.json').exists():raise FileExistsError('completed collection already exists')
        timeout=config.get('collection_timeout_seconds',600)
        if type(timeout)!=int or not 1<=timeout<=3600:raise ValueError('collection timeout must be 1..3600 seconds')
        attempt=1+len(list(state.glob('collection-*.partial.tar')))
        partial=state/f'collection-{attempt:03d}.partial.tar'
        try:
            with partial.open('xb') as stream:
                ssh(config,'tar -C '+shlex.quote(spec['remote'])+' -cf - .',stdout=stream,timeout=timeout)
        except Exception as error:
            write(state/f'collection-{attempt:03d}.failure.json',{'job_id':receipt['job_id'],'error_type':type(error).__name__,'partial_bytes':partial.stat().st_size if partial.exists() else 0,'status':'incomplete; same owned job may be recollected'})
            raise
        partial.rename(destination)
        result={'job_id':receipt['job_id'],'archive_sha256':digest(destination),'bytes':destination.stat().st_size,'terminal_status':'must_check_scheduler_and_pipeline_exit'}
        write(state/'collection_receipt.json',result);return result
    raise ValueError(action)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['plan','stage','submit','status','collect']);p.add_argument('--config',type=Path,required=True)
    p.add_argument('--grant',type=Path);p.add_argument('--run-id',required=True);p.add_argument('--state',type=Path,required=True);p.add_argument('--payload',type=Path)
    a=p.parse_args();print(json.dumps(run(a.action,load(a.config),a.run_id,a.state,a.payload,load(a.grant) if a.grant else None),ensure_ascii=False,indent=2))
if __name__=='__main__':main()
