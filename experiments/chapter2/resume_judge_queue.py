"""Resume only never-transmitted calibration queue records; preserve prior states."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json

import judge_calibration as jc
from judge_api_adapter import digest
from models import encoded, sha, now
from transport_retry import RetryingClient, RetryPolicy, atomic


def run():
    ph,p,out,packets=jc.verify()
    jc.require(not jc.read(jc.AUTH)['authorized'],'Existing dispatch still open')
    selected=[]
    for s in p['sample_ids']:
        path=out/'gpt_sol'/s/'result.json';r=jc.read(path)
        if r['status']!='technical_unresolved':continue
        q=jc.read(path.parent/'requests/000.json')
        if q['transport_attempts']!=0:continue
        jc.require(r['transport_status']==q['status']=='deployment_halted','Only untouched queued requests may resume')
        selected.append(dict(sample_id=s,result=path.relative_to(jc.EXPERIMENT).as_posix(),
                             result_sha256=sha(path.read_bytes()),request_sha256=sha((path.parent/'requests/000.json').read_bytes())))
    jc.require(len(selected)==10,'Expected exactly the ten unsent requests; no repeated recovery')
    manifest=dict(schema='judge_queue_resume_v1',prepared_utc=now(),base_protocol_sha256=ph,
                  source_sha256=sha(Path(__file__).read_bytes()),selected=selected,
                  rule='Only original transport_attempts=0 records resume; the exhausted three-attempt record is not retried; score contract unchanged',
                  original_answers_repeated=False,rubric_changed=False,request_body_changed=False,
                  max_attempts=3,acceptance_started=False,full_generation_started=False)
    h=digest(manifest);root=jc.EXPERIMENT/'release/frozen/judge_queue_recovery'/h;root.mkdir(parents=True,exist_ok=False)
    (root/'00.py').write_bytes(Path(__file__).read_bytes());(root/'manifest.json').write_bytes(encoded(manifest))
    for row in selected:
        path=jc.EXPERIMENT/row['result'];q=path.parent/'requests/000.json'
        jc.require(sha(path.read_bytes())==row['result_sha256'] and sha(q.read_bytes())==row['request_sha256'],'Queue changed')
        archive=path.with_name('result_before_queue_resume.json')
        jc.require(not archive.exists(),'Never replace preserved states')
        path.rename(archive)
        q.with_name('request_before_queue_resume.json').write_bytes(q.read_bytes())
    a=jc.read(jc.AUTH);a.update(authorized=True,sample_ids=[x['sample_id'] for x in selected],judges=['gpt_sol'],
                              authorized_utc=now(),queue_recovery_sha256=h,authorization_scope='same authorized calibration, ten never-sent tasks only')
    atomic(jc.AUTH,a)
    profile=jc.calibration_profile('gpt_sol',p['judge_output_token_cap'])
    client=RetryingClient(jc.load_deployment('gpt_sol',profile,p['concurrency']['gpt_sol']),RetryPolicy())
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            result=list(pool.map(lambda row:jc.run_one(ph,p,out,packets[row['sample_id']],'gpt_sol',profile,client),selected))
        return dict(resumed=10,statuses=result,execution_overlay_sha256=h)
    finally:
        a=jc.read(jc.AUTH);a.update(authorized=False,ended_utc=now());atomic(jc.AUTH,a)
        (root/'completion.json').write_bytes(encoded(dict(ended_utc=now(),authorized=False,all_dispatch_closed=True)))


if __name__=='__main__':print(json.dumps(run(),ensure_ascii=False))
