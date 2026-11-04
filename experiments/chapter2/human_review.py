"""Offline, score-side human packets. Never imported by the generation worker."""
from pathlib import Path
import argparse,collections,hashlib,json,re
from matrix import DATASET,tasks
from models import WORK,EXPERIMENT,encoded,sha,now
from judge_contract import VERSION,validate,joint_metrics

ROOT=DATASET/'open/review/calibration'
SEED='chapter2-single-reviewer-60-60-20261103'
ARMS=[('graph','single_pass'),('graph','agentic'),('bm25','single_pass'),('bm25','agentic'),('direct','direct')]

def digest(value):return sha(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode())
def read(p):return json.loads(Path(p).read_text('utf-8'))

def prepare():
    ROOT.mkdir(parents=True,exist_ok=True)
    if (ROOT/'administration/sample_mapping.json').exists():raise FileExistsError('Preserve the current sampling plan; do not overwrite human work')
    selection=read(DATASET/'open/review/selection.json')['items']
    questions={q['id']:q for q in read(DATASET/'open/model/questions.json')}
    gold={a['id']:a for a in read(DATASET/'open/scoring/annotations.json')};evidence=read(DATASET/'open/scoring/evidence.json')
    index={(r['model'],r['id'],r['method'],r['mode'],r['budget']):r for r in tasks() if r['part']=='open'}
    pools={p:{} for p in ('calibration','acceptance')}
    for i,cap in enumerate(['S0','S1','M0','M1']):
        ids=sorted([q['id'] for q in selection if q['capability']==cap],key=lambda q:digest([SEED,q]))
        cut=12+i%2;pools['calibration'][cap]=ids[:cut];pools['acceptance'][cap]=ids[cut:]
    mapping=[]
    for phase in ('calibration','acceptance'):
        packets=[];nondirect=0
        for cap in ('S0','S1','M0','M1'):
            slot=0
            for model in ('qwen3-8b','qwen3-14b','llama3.1-8b'):
                for method,mode in ARMS:
                    qid=pools[phase][cap][slot%len(pools[phase][cap])];slot+=1
                    budget=None if method=='direct' else ('S','M','L')[nondirect%3]
                    if method!='direct':nondirect+=1
                    task=index[(model,qid,method,mode,budget)];sample='R-'+digest([SEED,phase,task['task_id']])[:12]
                    a=gold[qid];q=questions[qid]
                    row=dict(sample_id=sample,phase=phase,capability=cap,task=task,question_sha256=digest(q),annotation_sha256=digest(a))
                    mapping.append(row)
                    packets.append(dict(sample_id=sample,question=q['question'],question_id=qid,question_sha256=row['question_sha256'],
                        annotation_sha256=row['annotation_sha256'],conditional=a['labels']['condition_discrimination'],
                        criteria=[dict(criterion_id=p['id'],claim=p['claim'],evidence_ids=p['evidence_ids']) for p in a['required_points']],
                        sources=[dict(evidence_id=eid,**evidence[eid]) for eid in a['required_evidence_ids']],
                        applicability=a['applicability'],acceptable_answer_range=a['acceptable_answer_range'],critical_errors=a['critical_errors'],
                        answer=None,answer_sha256=None,generation_failed=None,binding_status='awaiting_generation'))
        # Display order is independent of model/method/class, and exposes no AI grades.
        packets.sort(key=lambda p:digest([SEED,'display',p['sample_id']]))
        folder=ROOT/phase;folder.mkdir(exist_ok=True)
        (folder/'packets.json').write_bytes(encoded(dict(schema='human_review_packets_v1',phase=phase,enabled_for_review=phase=='calibration',
            dataset_sha256=read(DATASET/'binding.json')['dataset_sha256'],samples=packets)))
        templates=[dict(sample_id=p['sample_id'],reviewer=None,reviewed_utc=None,packet_sha256=None,
            record=dict(schema_version=VERSION,sample_id=p['sample_id'],judge_id='human',judge_version='single-human-reference-v1',status='pending',
                points=[dict(criterion_id=c['criterion_id'],score=None,reason='',answer_quote='') for c in p['criteria']],
                fact_gate=None,applicability_gate=None if p['conditional'] else 'not_applicable',reason='')) for p in packets]
        (folder/'blank_labels.json').write_bytes(encoded(dict(schema='human_review_labels_v1',phase=phase,labels=templates)))
    admin=ROOT/'administration';admin.mkdir(exist_ok=True)
    plan=dict(schema='single_human_sampling_v1',created_utc=now(),seed=SEED,dataset_sha256=read(DATASET/'binding.json')['dataset_sha256'],
        basis='Preselected without responses or AI scores; phases share no question IDs; no formal dataset split',
        human_reviewers=1,calibration=60,acceptance=60,answer_tasks_unique=True,pools=pools,samples=mapping,
        thresholds=dict(EAS_arith_MAE_max=5,EAS_arith_absolute_bias_max=3,K_F_A_within_025_min=.9),
        acceptance_locked=True,human_labels_completed=0)
    (admin/'sample_mapping.json').write_bytes(encoded(plan))
    verify_plan(plan)
    return dict(samples=120,calibration=60,acceptance=60,human_labels=0,formal_answers_bound=0)

def verify_plan(plan=None):
    plan=plan or read(ROOT/'administration/sample_mapping.json');allids=[];phaseids={}
    for phase in ('calibration','acceptance'):
        rows=[r for r in plan['samples'] if r['phase']==phase];assert len(rows)==60
        cells=[(r['task']['model'],r['capability'],r['task']['method'],r['task']['mode']) for r in rows];assert len(set(cells))==60
        assert collections.Counter(r['task']['budget'] for r in rows)=={None:12,'S':16,'M':16,'L':16}
        counts=collections.Counter(r['task']['id'] for r in rows);assert len(counts)==50 and max(counts.values())==2
        phaseids[phase]=set(counts);allids += [r['task']['task_id'] for r in rows]
    assert len(set(allids))==120 and not phaseids['calibration']&phaseids['acceptance']
    if plan['dataset_sha256']!=read(DATASET/'binding.json')['dataset_sha256']:raise ValueError('Review dataset drift')
    questions={q['id']:q for q in read(DATASET/'open/model/questions.json')};gold={a['id']:a for a in read(DATASET/'open/scoring/annotations.json')}
    evidence=read(DATASET/'open/scoring/evidence.json')
    for phase in ('calibration','acceptance'):
        packets={p['sample_id']:p for p in read(ROOT/phase/'packets.json')['samples']}
        rows=[r for r in plan['samples'] if r['phase']==phase]
        if set(packets)!={r['sample_id'] for r in rows}:raise ValueError('Packet IDs mismatch')
        for r in rows:
            p=packets[r['sample_id']];q=questions[r['task']['id']];a=gold[r['task']['id']]
            if digest(q)!=r['question_sha256'] or digest(a)!=r['annotation_sha256']:raise ValueError('Question/Gold drift')
            if p['question']!=q['question'] or p['question_id']!=q['id'] or p['annotation_sha256']!=r['annotation_sha256'] or p['question_sha256']!=r['question_sha256']:raise ValueError('Packet question/Gold mismatch')
            criteria=[dict(criterion_id=x['id'],claim=x['claim'],evidence_ids=x['evidence_ids']) for x in a['required_points']]
            if p['criteria']!=criteria or p['sources']!=[dict(evidence_id=eid,**evidence[eid]) for eid in a['required_evidence_ids']]:raise ValueError('Packet scoring basis mismatch')
    return True

def bind(run_root,phase):
    cancelled=EXPERIMENT/'release/planning/review_workflow.json'
    if phase=='acceptance' and cancelled.exists() and read(cancelled).get('acceptance_cancelled'):
        raise PermissionError('Extra acceptance was cancelled by the owner; use the full experiment entry')
    verify_plan()
    plan=read(ROOT/'administration/sample_mapping.json');path=ROOT/phase/'packets.json';pack=read(path)
    byid={r['sample_id']:r for r in plan['samples'] if r['phase']==phase};root=Path(run_root).resolve();bound=0
    for p in pack['samples']:
        row=byid[p['sample_id']];task=row['task'];source=root/task['model']/task['task_id']/'result.json'
        if not source.exists():continue
        r=read(source)
        if r['task']!=task:raise ValueError('Task mapping mismatch')
        protocol=EXPERIMENT/'release/planning/run_protocol.json'
        if r['protocol_sha256']!=sha(protocol.read_bytes()):raise ValueError('Response protocol mismatch')
        if r['status'] in {'outcome_unknown','http_result_unknown','usage_unknown','deployment_halted','runner_error'}:continue
        answer=r.get('answer') if r['status']=='answered' else '[未生成有效回答：'+r['status']+']'
        if not isinstance(answer,str) or not answer.strip():raise ValueError('Missing response')
        ah=sha(answer.encode())
        if p['answer_sha256'] and p['answer_sha256']!=ah:raise ValueError('Never overwrite an already bound answer')
        p.update(answer=answer,answer_sha256=ah,generation_failed=r['status']!='answered',binding_status='bound')
        bound+=1
    path.write_bytes(encoded(pack));return dict(bound=bound,phase=phase)

def validate_labels(path,phase):
    verify_plan()
    pack=read(ROOT/phase/'packets.json')
    if not pack['enabled_for_review']:raise ValueError('Acceptance is locked until judge/rubric freeze')
    if phase=='acceptance':
        lock=ROOT/'administration/acceptance_lock.json';locked=read(lock)
        if pack.get('rubric_lock_sha256')!=sha(lock.read_bytes()):raise ValueError('Acceptance lock mismatch')
        for name,h in locked['files'].items():
            if sha((WORK/name).read_bytes())!=h:raise ValueError('Locked judge/rubric changed; acceptance cannot be reused')
    expected={p['sample_id']:p for p in pack['samples']};document=read(path)
    if document.get('schema')!='human_review_labels_v1' or document.get('phase')!=phase:raise ValueError('Wrong label schema/phase')
    rows=document['labels'];ids=[r['sample_id'] for r in rows]
    if len(ids)!=60 or len(set(ids))!=60 or set(ids)!=set(expected):raise ValueError('Exactly 60 matching unique labels required')
    metrics=[]
    for row in rows:
        p=expected[row['sample_id']]
        if p['binding_status']!='bound' or not p['answer_sha256']:raise ValueError('Real answer not yet bound')
        if row.get('packet_sha256')!=digest(p):raise ValueError('Human label packet mismatch')
        if not isinstance(row.get('reviewer'),str) or not row['reviewer'].strip() or not isinstance(row.get('reviewed_utc'),str) or not row['reviewed_utc'].strip():raise ValueError('Real reviewer and timestamp required')
        if row['record'].get('judge_id')!='human' or row['record'].get('sample_id')!=row['sample_id']:raise ValueError('Human identity mismatch')
        validate(row['record'],expected=[c['criterion_id'] for c in p['criteria']],conditional=p['conditional'])
        metrics.append(joint_metrics(row['record'],[c['criterion_id'] for c in p['criteria']],p['conditional'],p['generation_failed']))
    if len({r['reviewer'].strip() for r in rows})!=1:raise ValueError('This protocol specifies one human reviewer')
    return dict(phase=phase,complete=60,metrics=metrics)

def freeze(labels):
    cancelled=EXPERIMENT/'release/planning/review_workflow.json'
    if cancelled.exists() and read(cancelled).get('acceptance_cancelled'):
        raise PermissionError('Extra acceptance is cancelled; freeze the formal full protocol instead')
    validate_labels(labels,'calibration')
    lock=ROOT/'administration/acceptance_lock.json'
    if lock.exists():raise FileExistsError('Acceptance already unlocked; do not tune then reuse these answers')
    files=[Path(__file__).with_name(n) for n in ('judge_prompt.txt','scoring_rules.json')]+[WORK/'PrincipiaBlastFoam-DSH/config/llm'/n for n in ('judging.yaml','models.yaml')]
    lock.write_bytes(encoded(dict(locked_utc=now(),calibration_labels_sha256=sha(Path(labels).read_bytes()),
        files={p.relative_to(WORK).as_posix():sha(p.read_bytes()) for p in files},
        rule='No adjustment using these acceptance answers; retain failed acceptance and select a new preregistered panel if revised.')))
    path=ROOT/'acceptance/packets.json';p=read(path);p['enabled_for_review']=True;p['rubric_lock_sha256']=sha(lock.read_bytes());path.write_bytes(encoded(p))
    return dict(acceptance_unlocked=True)

def main():
    a=argparse.ArgumentParser(description=__doc__);a.add_argument('command',choices=['prepare','verify','bind','validate-labels','freeze-acceptance']);a.add_argument('--phase',choices=['calibration','acceptance'],default='calibration');a.add_argument('--path');v=a.parse_args()
    if v.command=='prepare':result=prepare()
    elif v.command=='verify':result=dict(plan_valid=verify_plan())
    else:
        if not v.path:a.error('--path required')
        result=bind(v.path,v.phase) if v.command=='bind' else validate_labels(v.path,v.phase) if v.command=='validate-labels' else freeze(v.path)
    print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':main()
