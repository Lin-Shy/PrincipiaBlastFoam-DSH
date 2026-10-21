"""Audit all 600 fresh revision sessions using the frozen source/request auditor."""
import argparse
from collections import Counter
import json
from pathlib import Path
from chapter2_optimization_200 import DATASET, read, save, sha
from chapter2_publication_200 import verify
from chapter2_publication_generation_report import audit_session


def audit(root):
    p=verify(root);questions={q['id']:q['question'] for q in read(root/'public-questions.json')}
    if len(questions)!=200 or p['generation_sessions']!=600:raise ValueError('Wrong grid')
    controller=read(root/'generation-controller-completion.json')
    if not controller['complete'] or controller['protocol_sha256']!=sha(root/'protocol.json'):
        raise ValueError('Generation incomplete')
    if sha(DATASET/'model/questions.json')!=p['questions_sha256'] or sha(DATASET/'binding.json')!=p['dataset_binding_sha256']:
        raise ValueError('Bank drift')
    if sha(root/'provenance/adopted-chapter02.md')!=p['design_sha256']:raise ValueError('Design drift')
    for rel,digest in p['implementation_sha256'].items():
        if sha(root/'runtime'/rel)!=digest:raise ValueError('Runtime snapshot drift')
    cache={};rows=[];by_arm={};requests=Counter();usage=Counter();unknown=0
    for arm in p['arms']:
        completion=read(root/'completion'/(arm+'.json'));statuses=Counter()
        if completion['sessions']!=200 or set(completion['results_sha256'])!=set(questions):raise ValueError('Arm incomplete')
        if completion['protocol_sha256']!=sha(root/'protocol.json'):raise ValueError('Completion drift')
        for qid,question in questions.items():
            result=read(root/'generation'/arm/qid/'result.json')
            a=audit_session(root,arm,qid,question,p,cache)
            if a['result_sha256']!=completion['results_sha256'][qid]:raise ValueError('Result drift')
            statuses[result['status']]+=1;requests.update(a['request_statuses']);usage.update(a['known_usage'])
            unknown+=a['unknown_usage_requests']
            rows.append(dict(arm=arm,id=qid,question=question,status=result['status'],answer=result['answer'],
                references=result['references'],references_delivered=result.get('references_delivered'),
                result_sha256=a['result_sha256']))
        if completion['statuses']!=dict(statuses):raise ValueError('Status drift')
        by_arm[arm]=dict(registered=200,closed=200,statuses=dict(statuses))
    target=root/'answers.jsonl'
    data=''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in rows)
    if target.exists():
        if target.read_text(encoding='utf-8')!=data:raise ValueError('Existing answer export drift')
    else:target.write_text(data,encoding='utf-8')
    summary=dict(schema='revision200_generation_audit_v2',registered=600,closed=600,
        generation_complete=True,by_arm=by_arm,protocol_sha256=sha(root/'protocol.json'),
        answers_jsonl_sha256=sha(target),physical_requests=sum(requests.values()),request_statuses=dict(requests),
        known_usage=dict(usage),requests_with_unknown_usage=unknown,configured_worker_bound=6,
        concurrency_note='Three isolated processes, two blocking request workers each; no replay. Wall-clock starts plus monotonic durations are not a physical concurrency measurement.',
        audit_script_sha256=sha(Path(__file__)))
    save(root/'generation-audit.json',summary)
    print(json.dumps(summary,ensure_ascii=False),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--root',type=Path,required=True)
    audit(parser.parse_args().root.resolve())
