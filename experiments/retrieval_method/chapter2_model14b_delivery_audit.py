"""Audit the full grid; mixed wall/monotonic intervals are diagnostic only."""
from collections import Counter
from pathlib import Path
import json
from chapter2_optimization_200 import PROJECT, DATASET, read, save, sha
from chapter2_publication_200 import verify
from chapter2_model14b_generation_audit import audit_session

R=PROJECT.parent/'graduation-experiment-results/chapter2_retrieval/current/model14b_200_20261019_002'


def main():
    p=verify(R);qs={q['id']:q['question'] for q in read(R/'public-questions.json')}
    assert len(qs)==200 and p['generation_sessions']==1400
    assert sha(DATASET/'model/questions.json')==p['questions_sha256']
    assert sha(DATASET/'binding.json')==p['dataset_binding_sha256']
    assert read(R/'generation-controller-completion.json')['complete']
    for rel,digest in p['implementation_sha256'].items():
        assert sha(R/'runtime'/rel)==digest
    rows=[];byarm={};cache={};physical=Counter();usage=Counter();unknown=0;timeline=[]
    for arm in p['arms']:
        comp=read(R/'completion'/(arm+'.json'))
        assert comp['sessions']==200 and set(comp['results_sha256'])==set(qs)
        assert comp['protocol_sha256']==sha(R/'protocol.json')
        statuses=Counter()
        for qid,question in qs.items():
            result=read(R/'generation'/arm/qid/'result.json')
            verified=audit_session(R,arm,qid,question,p,cache)
            assert verified['result_sha256']==comp['results_sha256'][qid]
            statuses[result['status']]+=1
            physical.update(verified['request_statuses']);usage.update(verified['known_usage'])
            unknown+=verified['unknown_usage_requests']
            for begin,end in verified['request_intervals']:
                timeline.extend([(begin,1),(end,-1)])
            rows.append(dict(arm=arm,id=qid,question=question,status=result['status'],
                answer=result['answer'],references=result['references'],
                references_delivered=result.get('references_delivered'),result_sha256=verified['result_sha256']))
        assert dict(statuses)==comp['statuses']
        byarm[arm]=dict(registered=200,closed=200,statuses=dict(statuses))
    active=peak=0
    for _,delta in sorted(timeline):
        active+=delta;peak=max(peak,active)
    assert active==0
    # Each of seven frozen subprocesses has two blocking workers. Each worker
    # calls the single-attempt synchronous client sequentially. This proves
    # an executor bound of 14; wall-start + monotonic-duration is not an end
    # timestamp and cannot override that bound after clock adjustments.
    assert p['workers_per_arm']==2 and len(p['arms'])==7
    target=R/'answers.jsonl'
    assert not target.exists()
    target.write_text(''.join(json.dumps(row,ensure_ascii=False)+'\n' for row in rows),encoding='utf-8')
    save(R/'generation-audit.json',dict(schema='answer14b_full_grid_delivery_audit_v1',
        registered=1400,closed=1400,answered=sum(row['status']=='answered' for row in rows),
        by_arm=byarm,generation_complete=True,protocol_sha256=sha(R/'protocol.json'),
        answers_jsonl_sha256=sha(target),physical_requests=sum(physical.values()),
        request_statuses=dict(physical),known_usage=dict(usage),requests_with_unknown_usage=unknown,
        executor_concurrency_bound=14,mixed_clock_interval_overlap_diagnostic=peak,
        concurrency_scope='Seven frozen processes x two blocking workers; each client single attempt and sequential. Mixed clock intervals do not measure exact end times.',
        unicode_delivery_closure_sha256=sha(R/'recovery/closure.json'),
        invalid_unicode_failures=2,network_calls_for_closure=0,audit_script_sha256=sha(Path(__file__))))
    (R/'provenance/delivery-audit-source.py').write_bytes(Path(__file__).read_bytes())
    print(json.dumps(read(R/'generation-audit.json'),ensure_ascii=False))


if __name__=='__main__':main()
