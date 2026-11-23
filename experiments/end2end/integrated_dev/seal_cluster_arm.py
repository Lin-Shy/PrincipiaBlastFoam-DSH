"""Archive a finished chapter arm, including a continued session, without recomputation."""
import json
import sys
import zipfile
from cluster_first import batch,files,read,write,sha

def seal(task,arm):
    root=batch/'cluster_live'/task/arm
    continued=(root/'continuation-01').exists()
    segment=root/'continuation-01' if continued else root
    exit_record=read(segment/('exit.json' if continued else 'attempt_exit.json'))
    ledger=read(segment/'provider_ledger/ledger.json')
    events=ledger['events']
    assert len(events)<=100 and [e['request'] for e in events]==list(range(1,len(events)+1))
    state=segment/'operator_cluster'
    output=root/'workspace/delivery';manifest=files(output)
    with zipfile.ZipFile(root/'submission.zip','x',compression=zipfile.ZIP_DEFLATED) as z:
        for name,h in manifest.items():
            assert sha(output/name)==h
            z.write(output/name,name)
    job=read(state/'job_receipt.json') if (state/'job_receipt.json').exists() else None
    assert job or not (state/'submit_intent.json').exists(), 'reconcile job before conclusion'
    cost=dict(provider_requests=len(events),model_tokens=sum(e['usage']['total_tokens'] for e in events if e.get('usage')),
        unsettled=[e['request'] for e in events if not e.get('usage')],actual_money=None,cluster_jobs=int(bool(job)),
        allocated_node_minutes=None if job else 0)
    record=dict(session=(read(root/'request14_closeout.json')['session_id'] if continued else read(root/'native_outcome.json')['session_id']),
        exit=exit_record,requests_limit=ledger['max_requests'],files=manifest,archive_sha256=sha(root/'submission.zip'),
        stage_intent=(state/'stage_intent.json').exists(),submit_intent=(state/'submit_intent.json').exists(),job=job,cost=cost)
    write(root/'sealed.json',record)
    d=batch/'attempts'/arm/task/'first'
    for name,changes in [('cost',cost),('status',dict(status='已运行并封存',verdict='待交件核验' if manifest else '无交件',
        authorization='authorization.json',run_evidence=(root/'sealed.json').relative_to(batch).as_posix(),
        submission=(root/'submission.zip').relative_to(batch).as_posix() if manifest else None,blocker=None))]:
        p=d/(name+'.json');v=read(p);v.update(changes);tmp=p.with_suffix('.new');write(tmp,v);tmp.replace(p)
    print(json.dumps(record,ensure_ascii=False))

if __name__=='__main__':seal(*sys.argv[1:])
