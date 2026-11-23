"""Operator-only budget diagnostic. Fresh sessions, immutable delivery snapshots."""
import hashlib
import shutil
import sys
import zipfile
from pathlib import Path
from local_remaining_v2 import (HERE, WS, base, batch, runtime, sha, write, read, files,
    common_environment, launch_attempt, snapshot_runtime, runtime_digest, dispatch)

dest = base/'budget_diagnostic_20261119'
order = [('B11','general'),('B11','professional'),('B20','professional'),('B20','general')]

def capture(root, label):
    delivery = root/'workspace/delivery'
    saved = {}
    for p in sorted(delivery.rglob('*')):
        if p.is_symlink() or getattr(p.lstat(),'st_file_attributes',0)&1024:
            raise ValueError('linked delivery')
        if p.is_file():
            data = p.read_bytes()
            digest = hashlib.sha256(data).hexdigest()
            blob = root/'observer/blobs'/digest
            if not blob.exists():
                blob.write_bytes(data)
            saved[p.relative_to(delivery).as_posix()] = digest
    write(root/'observer'/(label+'.json'),saved)
    return saved

class Observe(launch_attempt.Gate):
    def call(self,body):
        previous = len(self.events)
        root = self.root.parent
        if not (root/'observer'/f'before-{previous+1}.json').exists():
            capture(root,f'before-{previous+1}')
        try:
            return super().call(body)
        finally:
            if previous==31 and len(self.events)==32:
                capture(root,'request32')

def main():
    dest.mkdir(exist_ok=False)
    write(dest/'authorization.json',dict(order=order,max_each=100,total=400,cluster_jobs=0,
        purpose='新预算诊断；四次独立新会话；沿用原题卡和首次系统。未知用量停止，不重发。',
        boundary='request32 after response before tool execution; before-N includes earlier tool results'))
    pins=read(batch/'local_live/version.json')
    tasks={r['id']:r for r in read(dispatch/'index.json')}
    fixed=read(batch/'tasks.json')
    launch_attempt.Gate=Observe
    snapshot_runtime.sha=runtime_digest
    launch_attempt.common_environment=lambda r:dict(common_environment(r),C3_PYTHON=sys.executable,C3_MODULE_PATH=str(HERE.parent),C3_RUNTIME=str(runtime))
    for short,arm in order:
        key='CH3-DEV-'+short
        row=tasks[key]
        pair=dest/key
        old=(base/'B11_dispatch_review_20261118/live' if short=='B11' else batch/'local_live'/key)/arm
        root=pair/arm
        assert all(sha(Path(p))==h for p,h in pins.items())
        src=batch/'work'/arm/key/'first/input'
        package=dispatch/row['zip']
        assert sha(package)==row['sha256']
        with zipfile.ZipFile(package) as z:
            assert files(src)=={n:hashlib.sha256(z.read(n)).hexdigest() for n in z.namelist() if not n.endswith('/')}
        root.mkdir(parents=True)
        shutil.copytree(src,root/'workspace')
        for folder in ['workspace/common','workspace/delivery','home','tmp','user','cache','agents_home','observer/blobs']:
            (root/folder).mkdir(parents=True)
        shutil.copytree(old/'skills',root/'skills')
        shutil.copyfile(old/'prompt.txt',root/'prompt.txt')
        config=(old/'dump.yml').read_text(encoding='utf8')
        (root/'dump.yml').write_text(config.replace(str(old),str(root)),encoding='utf8')
        if not (pair/'manifest.json').exists():
            write(pair/'manifest.json',dict(task=key,source_sha256=pins,package_sha256=row['sha256'],
                grading_sha256=next(r['grading_sha256'] for r in fixed if r['id']==key)))
        binding=read(base/'pilot_decision_20261117'/f'{arm}.binding.json')
        binding.pop('cluster')
        grant=read(old/'attempt_intent.json')['authorization']
        grant.update(max_requests_per_arm=100,pair_manifest_sha256=sha(pair/'manifest.json'),
            authorization_evidence='budget_diagnostic_20261119/authorization.json')
        print('START',short,arm,flush=True)
        code=launch_attempt.run(pair,arm,binding,grant)
        events=read(root/'provider_ledger/ledger.json')['events']
        archived=capture(root,'final')
        with zipfile.ZipFile(root/'submission.zip','x',compression=zipfile.ZIP_DEFLATED) as z:
            for name,h in archived.items():z.write(root/'observer/blobs'/h,name)
        unknown=[e['request'] for e in events if e['state']!='settled']
        write(root/'sealed.json',dict(exit=code,files=archived,archive_sha256=sha(root/'submission.zip'),
            requests=len(events),known_tokens=sum(e['usage']['total_tokens'] for e in events if e.get('usage')),
            unknown=unknown,money=None,cluster_jobs=0))
        print('SEALED',short,arm,len(events),len(archived),unknown,flush=True)
        if unknown or not events or code and len(events)<100:
            raise RuntimeError('stop for operator reconciliation')

if __name__ == '__main__':
    raise SystemExit('Closed budget diagnostic. Use the current task results in development_batch18_20261118/STATUS.md.')
