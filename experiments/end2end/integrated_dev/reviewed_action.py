"""Perform one specifically requested operator action after a payload review."""
import argparse
import hashlib
import json
import re
import shlex
import shutil
from pathlib import Path
from cluster_first import batch,base,read,write,files,sha,cluster_service

job=cluster_service.cluster_job

def run(task,arm,action,expected,stamp):
    key='CH3-DEV-'+task
    root=batch/'cluster_live'/key/arm
    segment=root/'continuation-01' if (root/'continuation-01').exists() else root
    state=segment/'operator_cluster'
    config=read(base/'pilot_decision_20261117/acceptance.config.json')
    config['wall_minutes']=90
    rid=f'c3-dev-{task.lower()}-{arm}-first-20261119'
    grant=dict(live_actions_allowed=True,run_ids=[rid],actions=[action],limits={k:config[k] for k in ['tasks','memory_mib','wall_minutes']})
    if action=='stage':
        request=read(state/'review_requested.json')
        assert sha(state/'review_requested.json')==expected
        frozen=state/'review_copy'
        assert files(frozen)==request
        job.run(action,config,rid,state,frozen,grant)
        write(state/'operator_review.json',dict(approved=True,files=request))
        return
    assert re.fullmatch(r'[0-9]+',stamp)
    assert read(state/(stamp+'.request.json'))==dict(action=action,run_id=rid)
    staged=read(state/'stage_receipt.json')
    assert staged['run_id']==rid and staged['payload_sha256']==sha(state/'payload.tar')
    if action=='submit':
        assert sha(state/'review_requested.json')==expected and not (state/'submit_intent.json').exists()
        approved=read(state/'review_requested.json')
        pairs={'batch.sh':sha(state/'batch.sh'),'payload.tar':staged['payload_sha256'],**{'payload/'+n:h for n,h in approved.items()}}
        assert all(re.fullmatch(r'[a-zA-Z0-9._/+-]+',n) for n in pairs)
        command='cd '+shlex.quote(staged['remote'])+' && sha256sum '+' '.join(map(shlex.quote,pairs))
        values=job.ssh(config,command,capture_output=True,text=True).stdout
        actual={n:h for h,n in (line.split(None,1) for line in values.splitlines())}
        assert actual==pairs
        write(state/'verified_remote.json',actual)
    result=job.run(action,config,rid,state,grant=grant)
    if action=='collect':
        target=root/'workspace/returned';target.mkdir(exist_ok=True)
        with (target/'collected.tar').open('xb') as output,(state/'collected.tar').open('rb') as source:
            shutil.copyfileobj(source,output)
        result['archive_in_workspace']='returned/collected.tar'
    write(state/(stamp+'.response.json'),result)
    print(action,result.get('job_id'),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('task');p.add_argument('arm',choices=['general','professional'])
    p.add_argument('action',choices=['stage','submit','status','collect']);p.add_argument('expected');p.add_argument('stamp',nargs='?',default='')
    run(**vars(p.parse_args()))
