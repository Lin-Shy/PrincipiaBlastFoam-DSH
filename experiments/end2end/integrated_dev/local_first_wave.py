"""Serial operator queue for authorized local first attempts. No grading input."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import zipfile
from b11_live import HERE, WS, base, batch, runtime, arms, sha, write, common_environment, launch_attempt
import snapshot_runtime

def runtime_digest(path):
    state=hashlib.sha256()
    buffer=bytearray(65536)
    with snapshot_runtime.long_path(path).open('rb',buffering=0) as stream:
        while count:=stream.readinto(buffer):state.update(memoryview(buffer)[:count])
    return state.hexdigest()

read=lambda p:json.loads(p.read_bytes())
dispatch=WS/'graduation-datasets/chapter03_simulation_tasks/development_batch_20261118/dispatch'
queue=batch/'local_live'

def update(path,data):
    temp=path.with_suffix('.next')
    write(temp,data)
    temp.replace(path)

def files(path):
    return {f.relative_to(path).as_posix():sha(f) for f in path.rglob('*') if f.is_file()}

def main():
    snapshot_runtime.sha=runtime_digest
    auth=read(batch/'authorization.json')
    assert all(sha(batch/(key+'.json'))==auth[key+'_sha256'] for key in ('tasks','attempts'))
    tasks={r['id']:r for r in read(dispatch/'index.json')}
    attempts=[r for r in read(batch/'attempts.json') if not r['proposed_cluster_jobs'] and r['id']!='CH3-DEV-B11']
    assert len(attempts)==18 and len({r['attempt_id'] for r in attempts})==18
    queue.mkdir(exist_ok=True)
    fixed=[HERE/'pressure-tool.mjs',HERE/'engineering-delivery/SKILL.md',WS/'PrincipiaBlastFoam-DSH/.dsh/skills/blastfoam-quality-review/SKILL.md',HERE.parent/'native_attempt.mjs',HERE.parent/'launch_attempt.py',HERE.parent/'model_budget.py',HERE.parent/'professional/observe.py',HERE.parent/'pressure_observations.py',HERE/'local_first_wave.py',base/'pilot_decision_20261117/pair_final/general/dump.yml']
    pins={str(p):sha(p) for p in fixed}
    if (queue/'version.json').exists():assert read(queue/'version.json')==pins
    else:write(queue/'version.json',pins)
    for row in attempts:
        key,arm=row['id'],row['system']
        assert arm in arms
        task=tasks[key];pair=queue/key;root=pair/arm
        status_path=batch/row['status_file'];status=read(status_path)
        if (root/'sealed.json').exists():
            receipt=read(root/'sealed.json')
            assert receipt['settled'] and status.get('run_evidence') and sha(root/'submission.zip')==receipt['archive_sha256']
            continue
        if root.exists() or status.get('run_evidence') or status.get('submission') or status['status']!='已领包／未启动':raise RuntimeError('reconcile existing attempt: '+str(root))
        source=batch/status['public_input'];package=dispatch/task['zip']
        assert sha(package)==task['sha256']
        with zipfile.ZipFile(package) as z:expected={n:hashlib.sha256(z.read(n)).hexdigest() for n in z.namelist() if not n.endswith('/')}
        assert files(source)==expected
        assert all(sha(Path(p))==h for p,h in pins.items())
        root.mkdir(parents=True)
        shutil.copytree(source,root/'workspace')
        assert files(root/'workspace')==expected
        for sub in ['workspace/common','workspace/delivery','home','tmp','user','cache','agents_home','skills']:(root/sub).mkdir()
        template=base/'pilot_decision_20261117/pair_final/general'
        config=(template/'dump.yml').read_text(encoding='utf-8').replace(str(template),str(root))
        if arm=='professional':
            for skill in [HERE/'engineering-delivery',WS/'PrincipiaBlastFoam-DSH/.dsh/skills/blastfoam-quality-review']:
                shutil.copytree(skill,root/'skills'/skill.name)
            config+='\n- id: engineering-time-series\n  name: '+(HERE/'pressure-tool.mjs').as_uri()+'\n'
        (root/'dump.yml').write_text(config,encoding='utf-8')
        shutil.copyfile(base/'B11_dispatch_review_20261118/live'/arm/'prompt.txt',root/'prompt.txt')
        if not (pair/'manifest.json').exists():write(pair/'manifest.json',{'source_sha256':pins,'task':key,'public_zip_sha256':task['sha256']})
        binding=read(base/'pilot_decision_20261117'/f'{arm}.binding.json');binding.pop('cluster')
        cap=row['proposed_model_requests']
        grant=dict(live_model_allowed=True,arms=[arm],pair_manifest_sha256=sha(pair/'manifest.json'),authorization_evidence='approved batch '+row['attempt_id']+'; user extends same-host mode',isolation_accepted=True,isolation_evidence='distinct absolute work/home/output; shared host, not blind',complete_task_required=False,budget_unit='requests',max_requests_per_arm=cap,max_output_tokens=8192,wall_seconds=14400,generation=binding['generation'],**{k:binding[k] for k in ['model','context_window','endpoint_sha256']})
        launch_attempt.common_environment=lambda r:dict(common_environment(r),C3_PYTHON=sys.executable,C3_MODULE_PATH=str(HERE.parent),C3_RUNTIME=str(runtime))
        print('START',key,arm,cap,flush=True)
        code=launch_attempt.run(pair,arm,binding,grant)
        ledger=read(root/'provider_ledger/ledger.json');events=ledger['events']
        assert len(events)<=cap
        settled=bool(events) and all(e['state']=='settled' for e in events)
        delivered={}
        with zipfile.ZipFile(root/'submission.zip','x',compression=zipfile.ZIP_DEFLATED) as z:
            output=root/'workspace/delivery'
            for f in sorted(output.rglob('*')):
                if f.is_symlink() or getattr(f.lstat(),'st_file_attributes',0)&1024:raise RuntimeError('link in delivery')
                if f.is_file():
                    name=f.relative_to(output).as_posix();z.write(f,name);delivered[name]=sha(f)
        tokens=sum(e['usage']['total_tokens'] for e in events if e.get('usage'))
        receipt=dict(task=key,arm=arm,exit=code,requests=len(events),tokens_reported=tokens,settled=settled,unknown=[e['request'] for e in events if e['state']!='settled'],files=delivered,archive_sha256=sha(root/'submission.zip'),money=None,cluster_jobs=0)
        write(root/'sealed.json',receipt)
        ref=root.relative_to(batch).as_posix()
        status.update(status='已运行并封存',submission=ref+'/submission.zip' if delivered else None,run_evidence=ref+'/sealed.json',system_version_at_start='local_live/version.json',verdict='待独立评分' if delivered else '无交件',blocker=None if code==0 else ('本地请求上限' if settled and len(events)==cap else '检查模型/任务退出记录'))
        update(status_path,status)
        update(status_path.parent/'cost.json',dict(provider_requests=len(events),model_tokens=tokens,unsettled=receipt['unknown'],allocated_node_minutes=0,cluster_jobs=0,actual_money=None,attempt_wall_seconds=read(root/'attempt_exit.json')['wall_seconds']))
        print('SEALED',key,arm,code,len(events),len(delivered),flush=True)
        if not settled:raise RuntimeError('unsettled/unknown provider accounting; batch paused')
        if code!=0 and len(events)<cap:
            outcome=read(root/'native_outcome.json') if (root/'native_outcome.json').exists() else {}
            if '429' in str(outcome) or not outcome:raise RuntimeError('possible shared infrastructure failure')

if __name__=='__main__':main()
