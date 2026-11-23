"""Chapter 3 paired cluster task. Stage waits for operator review of exact files."""
import http.client
import shutil
import sys
import time
import urllib.error
from pathlib import Path

from local_remaining_v2 import (HERE, base, batch, runtime, dispatch, files, read, sha,
    write, snapshot_runtime, runtime_digest, launch_attempt, common_environment)
import cluster_service

class RetryGate(launch_attempt.Gate):
    def call(self, body):
        start=len(self.events)
        try:
            return super().call(body)
        except (urllib.error.URLError, http.client.RemoteDisconnected, http.client.IncompleteRead, TimeoutError) as error:
            if isinstance(error,urllib.error.HTTPError) or len(self.events)!=start+1 or len(self.events)>=self.limit:
                raise
            self.events[-1]['retry_disposition']='one new counted request on same task'
            self.save()
            self.closed=False
            return super().call(body)

class Reviewed(cluster_service.Service):
    def execute(self,body):
        if body.get('action')=='stage':
            source=(self.workspace/body.get('payload','payload')).resolve()
            if not source.is_relative_to(self.workspace) or not (source/'run_case.sh').is_file():
                raise ValueError('invalid payload')
            for p in [source,*source.rglob('*')]:
                if p.is_symlink() or getattr(p.lstat(),'st_file_attributes',0)&1024:
                    raise ValueError('linked payload')
            frozen=self.state/'review_copy'
            shutil.copytree(source,frozen)
            write(self.state/'review_requested.json',files(frozen))
            print('AWAITING PAYLOAD REVIEW',self.run_id,flush=True)
            for _ in range(600):
                decision=self.state/'operator_review.json'
                if decision.exists():
                    record=read(decision)
                    if record.get('approved') is not True or record.get('files')!=files(frozen):
                        raise PermissionError('payload review did not authorize staging')
                    return read(self.state/'stage_receipt.json')
                time.sleep(1)
            raise TimeoutError('operator review unavailable')
        action=body.get('action')
        if action=='plan':
            return super().execute(body)
        if action not in ('submit','status','collect'):
            raise ValueError('unsupported operation')
        # A different operator process owns the real SSH actions. A local file
        # cannot grant this service permission to submit a job.
        if not (self.state/'stage_receipt.json').exists():
            raise PermissionError('no reviewed staged payload')
        if action=='submit' and (self.state/'job_receipt.json').exists():
            return read(self.state/'job_receipt.json')
        stamp=str(time.time_ns())
        write(self.state/f'{stamp}.request.json',dict(action=action,run_id=self.run_id))
        print('OPERATOR ACTION',action,stamp,flush=True)
        for _ in range(600):
            response=self.state/f'{stamp}.response.json'
            if response.exists():return read(response)
            time.sleep(1)
        raise TimeoutError('operator action pending; reconcile JobID')

def main(short,arm):
    import zipfile,hashlib
    key='CH3-DEV-'+short
    row=next(a for a in read(batch/'attempts.json') if a['id']==key and a['system']==arm)
    assert row['proposed_cluster_jobs']==1 and row['proposed_model_requests']==100
    amendment=read(batch/'authorization.json')['cluster']
    assert key in amendment['first_attempt_tasks'] and arm in amendment['arms']
    assert len(set(amendment['first_attempt_tasks']))*len(set(amendment['arms']))*amendment['requests_per_arm']==amendment['cluster_batch_request_cap']==1600
    assert amendment['jobs_per_arm']==row['proposed_cluster_jobs'] and amendment['node_minutes_per_arm']==row['proposed_node_minutes']
    status=read(batch/row['status_file'])
    assert not status['run_evidence'] and not status['submission']
    pair=batch/'cluster_live'/key
    root=pair/arm
    old=base/'B11_dispatch_review_20261118/live'/arm
    pins=read(batch/'local_live/version.json')
    assert all(sha(Path(name))==h for name,h in pins.items())
    task=next(t for t in read(dispatch/'index.json') if t['id']==key)
    src=batch/status['public_input']
    package=dispatch/task['zip']
    assert sha(package)==task['sha256']
    with zipfile.ZipFile(package) as z:
        assert files(src)=={n:hashlib.sha256(z.read(n)).hexdigest() for n in z.namelist() if not n.endswith('/')}
    root.mkdir(parents=True,exist_ok=False)
    shutil.copytree(src,root/'workspace')
    for folder in ['workspace/common','workspace/delivery','home','tmp','user','cache','agents_home']:
        (root/folder).mkdir(parents=True)
    shutil.copytree(old/'skills',root/'skills')
    shutil.copyfile(HERE.parent/'cluster_client.py',root/'workspace/common/cluster_client.py')
    (root/'dump.yml').write_text((old/'dump.yml').read_text(encoding='utf8').replace(str(old),str(root)),encoding='utf8')
    (root/'prompt.txt').write_text('完成当前 TASK.md，交件放在 delivery/。仅用本题材料与本臂工具。计算只能在分配节点执行。共同操作入口为 python common/cluster_client.py plan|stage|submit|status|collect 。在 payload/ 准备算例及节点入口 run_case.sh（启动目录是远端作业根），stage 等待操作者审阅实际载荷。一个作业，提交应答未知时先查 JobID，不重提。禁止自行 SSH、访问凭据、评分资料或其他工作目录。',encoding='utf8')
    if not (pair/'manifest.json').exists():
        write(pair/'manifest.json',dict(task=key,public_sha256=task['sha256'],source_sha256=pins))
    prototype=base/'pilot_decision_20261117'
    binding=read(prototype/f'{arm}.binding.json')
    c=read(prototype/'acceptance.config.json')
    c['wall_minutes']=row['proposed_node_minutes']
    rid=f'c3-dev-{short.lower()}-{arm}-first-20261119'
    g=dict(live_actions_allowed=True,actions=['stage','submit','status','collect'],run_ids=[rid],
           limits={k:c[k] for k in ['tasks','wall_minutes','memory_mib']})
    binding['cluster']=dict(config=c,grant=g,run_id=rid)
    grant=read(old/'attempt_intent.json')['authorization']
    grant.update(max_requests_per_arm=amendment['requests_per_arm'],complete_task_required=True,
                 authorization_evidence='authorization.json: cluster first attempt',
                 cluster_authorization_evidence='batch authorization.json and attempts.json, reviewed payload required',
                 pair_manifest_sha256=sha(pair/'manifest.json'))
    launch_attempt.Gate=RetryGate
    cluster_service.Service=Reviewed
    snapshot_runtime.sha=runtime_digest
    launch_attempt.common_environment=lambda r:dict(common_environment(r),C3_PYTHON=sys.executable,C3_MODULE_PATH=str(HERE.parent),C3_RUNTIME=str(runtime))
    print('FORMAL',key,arm,flush=True)
    return launch_attempt.run(pair,arm,binding,grant)

if __name__=='__main__':sys.exit(main(*sys.argv[1:]))
