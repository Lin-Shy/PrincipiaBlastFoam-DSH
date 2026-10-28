"""Dev40 batch scoring with the unchanged, pre-audit frozen judge implementation.

Operational authorization is separate from the failed historical audit decision.
No human labels or method/model identity are included in judge packets.
"""
import runtime_layout as layout
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
import hashlib
import http.client
import json
from pathlib import Path
import ssl
import threading
import time
from urllib.parse import urlsplit

import scoring as core
import dev40_optimization as dev
from central_execution import DEFAULT_RUN, Registry, exclusive_lock, now
from judge_api_adapter import digest
from judge_contract import VERSION, calculate, joint_metrics
from scoring_review import guard_audit

ROOT=dev.ROOT/'scoring'
LOCK=threading.Lock()
JUDGES=core.JUDGES


def guard_operational():
    protocol=guard_audit(require_human=True)
    authority=core.read(core.ROOT/'operational_use.json')
    if not authority.get('dev40_scoring_authorized') or authority.get('test160_authorized'):
        raise PermissionError('Missing explicit Dev-only operational authorization')
    if authority['freeze_id']!=protocol['freeze']['freeze_id']:
        raise ValueError('Operational authorization bound to a different judge protocol')
    if authority['original_audit_acceptance_sha256']!=core.sha(core.ROOT/'audit/results/acceptance.json'):
        raise ValueError('Original audit decision changed')
    if core.read(core.ROOT/'audit/results/acceptance.json')['accepted'] is not False:
        raise ValueError('Failed original audit must remain recorded as failed')
    return authority


def prepare():
    authority=guard_operational()
    from dev40_report import report
    inventory=report()
    questions={q['id']:q['question'] for q in core.read(dev.QUESTIONS)}
    base=dev.SPLIT/'gold/dev40'
    annotations={q['id']:q for q in core.read(base/'annotations.json')}
    evidence=core.read(base/'evidence.json')
    if set(questions)!=set(annotations) or len(questions)!=40:raise ValueError('Dev40 identity mismatch')
    # Reuse exact anonymous packets for the original 30 calibration/audit answers.
    existing={}
    for name in ('calibration.json','audit/packet.json'):
        p=core.read(core.ROOT/name);private={r['sample_id']:r for r in p['private']}
        for item in p['items']:
            meta=private[item['sample_id']]
            existing[(meta['question_id'],meta['method_id'],meta['answer_sha256'])]=item
    sources={}
    for qid,a in annotations.items():
        rows=[];seen=set()
        for eid in a['required_evidence_ids']:
            e=evidence[eid]
            if e['path'] in seen:continue
            seen.add(e['path']);file=DEFAULT_RUN/'data/resources/corpus'/e['path']
            if core.sha(file)!=e['file_sha256']:raise ValueError('Frozen Gold source drift')
            text='\n'.join('%d|%s'%(n,line) for n,line in enumerate(core.longpath(file).read_text(encoding='utf-8-sig').splitlines(),1))
            rows.append(dict(path=e['path'],file_sha256=e['file_sha256'],text=text))
        sources[qid]=rows
    # Two calibration questions had additional frozen context files. Keep their
    # exact bundle for every method, rather than changing old requests to reuse them.
    for (qid,_,_),item in existing.items():
        required={evidence[eid]['path']:evidence[eid]['file_sha256'] for eid in annotations[qid]['required_evidence_ids']}
        actual={s['path']:s['file_sha256'] for s in item['sources']}
        if any(actual.get(name)!=value for name,value in required.items()):raise ValueError('Frozen packet lacks required source')
        for source in item['sources']:
            if core.sha(DEFAULT_RUN/'data/resources/corpus'/source['path'])!=source['file_sha256']:
                raise ValueError('Additional frozen context source drift')
        sources[qid]=item['sources']
    items=[];private=[]
    for r in inventory['records']:
        if r['status']=='not_run':continue
        file=DEFAULT_RUN/r['source_file'];raw=core.read(file)
        if core.sha(file)!=r['source_sha256'] or raw['id']!=r['question_id']:raise ValueError('Generation binding drift')
        qid=r['question_id'];a=annotations[qid]
        item=existing.get((qid,r['method'],r['source_sha256']))
        if item is not None:
            if item['answer']!=raw['answer'] or item['question']!=questions[qid]:raise ValueError('Reused text drift')
            if [c['claim'] for c in item['criteria']]!=[c['claim'] for c in a['required_points']]:raise ValueError('Reused Gold criteria drift')
            if item['conditional']!=a['labels']['condition_discrimination']:raise ValueError('Applicability drift')
            if {s['path']:s['file_sha256'] for s in item['sources']}!={s['path']:s['file_sha256'] for s in sources[qid]}:
                raise ValueError('Reused source set drift')
        else:
            sid='S'+hashlib.sha256((r['config_id']+'|'+qid+'|'+r['source_sha256']).encode()).hexdigest()[:16]
            item=dict(schema_version=VERSION,sample_id=sid,question=questions[qid],answer=raw.get('answer',''),
                generation_failed=r['generation_failed'],
                criteria=[dict(criterion_id='K%03d'%(n+1),claim=c['claim']) for n,c in enumerate(a['required_points'])],
                conditional=a['labels']['condition_discrimination'],sources=sources[qid])
        items.append(item)
        private.append(dict(sample_id=item['sample_id'],config_id=r['config_id'],question_id=qid,
            model=r['model'],method=r['method'],source_file=r['source_file'],source_sha256=r['source_sha256'],
            status=r['status'],item_sha256=digest(item)))
    if len({i['sample_id'] for i in items})!=len(items):raise ValueError('Duplicate anonymous sample')
    # Fit the frozen budget without losing any substantive source line. Apply the
    # same deterministic whitespace-only representation to every method for a QID.
    metadata={r['sample_id']:r for r in private};compact=set()
    for item in items:
        if item['generation_failed']:continue
        try:request_for('gpt_sol',item)
        except ValueError as exc:
            if 'exceeds judge input cap' not in str(exc):raise
            compact.add(metadata[item['sample_id']]['question_id'])
    for item in items:
        if metadata[item['sample_id']]['question_id'] not in compact:continue
        item['sources']=[dict(s,text='\n'.join(line for line in s['text'].splitlines() if line.partition('|')[2].strip())) for s in item['sources']]
        if not item['generation_failed']:request_for('gpt_sol',item)
        metadata[item['sample_id']]['item_sha256']=digest(item)
    packet=dict(schema_version=VERSION,items=items,private=private,fingerprints=core.fingerprint(),
        freeze_id=authority['freeze_id'],questions_sha256=core.sha(dev.QUESTIONS),
        gold_sha256={f:core.sha(base/f) for f in ('annotations.json','evidence.json')},test160_included=False,
        whitespace_compacted_questions=sorted(compact),
        source_policy='Full required source text, original numbered nonempty lines; blank numbered lines removed only when needed for frozen input cap. Same representation for all methods per question.')
    path=ROOT/'packet.json'
    historical=[]
    if path.exists():
        old=core.read(path);current={i['sample_id']:i for i in items}
        historical=old.get('historical_generation_failures',[])
        from dev40_recovery import active_recovery
        recovery=active_recovery(dev.ROOT)
        old_private={r['sample_id']:r for r in old['private']}
        for i in old['items']:
            if current.get(i['sample_id'])==i:continue
            sid=i['sample_id']
            if sid not in current and i['generation_failed'] and recovery:
                meta=old_private[sid]
                expected_source=str((dev.ROOT/recovery['baseline_file']).relative_to(DEFAULT_RUN))
                if (meta['config_id'],meta['question_id'],meta['source_file'],meta['source_sha256'])==(
                        recovery['config_id'],recovery['question_id'],expected_source,recovery['baseline_sha256']):
                    if any((ROOT/'requests'/j/sid).exists() or (ROOT/'reuse'/j/(sid+'.json')).exists() for j in JUDGES):
                        raise ValueError('Never supersede a previously judged answer')
                    historical.append(dict(item=i,private=meta,reason='One explicitly authorized recovery of unanswered connection refusal; original baseline unchanged'))
                    continue
            if sid not in current or any((ROOT/'requests'/j/sid).exists() or (ROOT/'reuse'/j/(sid+'.json')).exists() for j in JUDGES):
                raise ValueError('Previously requested scoring packet changed')
            old_lines={s['path']:[line for line in s['text'].splitlines() if line.partition('|')[2].strip()] for s in i['sources']}
            new_lines={s['path']:s['text'].splitlines() for s in current[sid]['sources']}
            if old_lines!=new_lines or {k:v for k,v in i.items() if k!='sources'}!={k:v for k,v in current[sid].items() if k!='sources'}:
                raise ValueError('Only whitespace-only compaction of unsent packets is allowed')
    if historical:packet['historical_generation_failures']=historical
    core.write(path,packet)
    print(json.dumps(dict(dev_scoring_answers=len(items),answered=sum(not i['generation_failed'] for i in items),
        original_audit_passed=False,operational_authorized=True)),flush=True)
    return packet


@lru_cache(maxsize=1)
def tokenizer():
    from tokenizers import Tokenizer
    return Tokenizer.from_file(str(DEFAULT_RUN/'data/resources/tokenizers/qwen3-14b/tokenizer.json'))


def request_for(judge,item):
    registry,profile,request=core.request_for(judge,item)
    messages=request['body'].get('messages',request['body'].get('input'))
    text=''.join('<|im_start|>'+m['role']+'\n'+m['content']+'<|im_end|>\n' for m in messages)+'<|im_start|>assistant\n'
    count=len(tokenizer().encode(text).ids)
    if count>profile['input_token_cap']:raise ValueError('Frozen source packet exceeds judge input cap')
    return registry,profile,request,count


def reused(judge,item):
    for folder in (core.ROOT/'requests',core.ROOT/'audit/requests'):
        for file in sorted((folder/judge/item['sample_id']).glob('attempt_*/parsed.json')):
            saved=core.read(file.parent/'request.json')
            _,profile,request,_=request_for(judge,item)
            if saved['fingerprint']!=core.fingerprint() or not layout.judge_request_matches(saved,profile,request):continue
            result=core.parse_current(profile,core.read(file.parent/'response.txt'),item)
            saved_parsed=core.read(file)
            if any(result.get(k)!=v for k,v in saved_parsed.items()):raise ValueError('Historical raw/parsed judge evidence mismatch')
            return dict(record=result['record'],source='existing_five_level',parsed_file=str(file.relative_to(DEFAULT_RUN)),
                parsed_sha256=core.sha(file),response_sha256=core.sha(file.parent/'response.txt'))
    return None


def collect(packet,verify=True):
    labels={j:{} for j in JUDGES};failures=[]
    for item in packet['items']:
        if item['generation_failed']:continue
        sid=item['sample_id']
        for judge in JUDGES:
            link=ROOT/'reuse'/judge/(sid+'.json')
            if link.exists():
                value=core.read(link);file=DEFAULT_RUN/value['parsed_file']
                if core.sha(file)!=value['parsed_sha256'] or core.sha(file.parent/'response.txt')!=value['response_sha256']:
                    raise ValueError('Reused judge evidence drift')
                if verify and not layout.path_records_equal(reused(judge,item),value):raise ValueError('Reused request/response differs')
                labels[judge][sid]=value['record'];continue
            valid=[]
            for file in sorted((ROOT/'requests'/judge/sid).glob('attempt_*/status.json')):
                state=core.read(file)
                if state['status']!='valid':failures.append(state);continue
                saved=core.read(file.parent/'request.json')
                _,profile,request,_=request_for(judge,item)
                if saved['fingerprint']!=core.fingerprint() or not layout.judge_request_matches(saved,profile,request):raise ValueError('Scoring request drift')
                parsed=core.read(file.parent/'parsed.json')
                if verify and core.parse_current(profile,core.read(file.parent/'response.txt'),item)!=parsed:
                    raise ValueError('Current raw/parsed response mismatch')
                valid.append(parsed['record'])
            if valid:labels[judge][sid]=valid[0]
    return labels,failures


def score(model=None,limit=None,retry_failed=False,workers=4):
    authority=guard_operational();packet=prepare();private={r['sample_id']:r for r in packet['private']}
    endpoint=authority.get('external_endpoint_authorization',{}).get('endpoint')
    if not endpoint or any(Registry().judge_profile(j)['base_url'].rstrip('/')!=endpoint.rstrip('/') for j in JUDGES):
        raise PermissionError('Explicit authorization for the configured external endpoint required')
    jobs=[];reuse_count=0
    for item in packet['items']:
        sid=item['sample_id']
        if item['generation_failed'] or model and private[sid]['model']!=model.replace('_','-'):continue
        for judge in JUDGES:
            found=reused(judge,item)
            if found:
                file=ROOT/'reuse'/judge/(sid+'.json')
                if file.exists() and core.read(file)!=found:raise ValueError('Judge reuse drift')
                core.write(file,found);reuse_count+=1;continue
            attempts=list((ROOT/'requests'/judge/sid).glob('attempt_*'))
            if any((a/'parsed.json').exists() and core.read(a/'status.json')['status']=='valid' for a in attempts):continue
            if attempts and (not retry_failed or len(attempts)>=2):continue
            if attempts and any(not (a/'status.json').exists() for a in attempts):raise ValueError('Partial request: reconcile before retry')
            jobs.append((judge,item))
    if limit:jobs=jobs[:limit]
    print(json.dumps(dict(reused_current_protocol=reuse_count,pending_requests=len(jobs),workers_per_judge=workers)),flush=True)
    if not jobs:return
    registry=Registry();keys={j:registry.private_key(j) for j in JUDGES}
    stop={j:threading.Event() for j in JUDGES}
    def worker(job):
        judge,item=job;sid=item['sample_id']
        if stop[judge].is_set():return
        try:_,profile,req,count=request_for(judge,item)
        except ValueError as exc:
            core.write(ROOT/'preflight'/judge/(sid+'.json'),dict(status='not_sent',sample_id=sid,judge=judge,reason=str(exc)))
            return
        with LOCK:
            ledger=core.rows(ROOT/'requests/ledger.jsonl')
            prior=[x for x in ledger if x['judge']==judge and x['sample_id']==sid]
            if len(prior)>=2 or len(ledger)>=4160:raise PermissionError('Finite Dev40 request quota exhausted')
            folder=ROOT/'requests'/judge/sid/('attempt_'+str(len(prior)+1));folder.mkdir(parents=True,exist_ok=False)
            core.write(folder/'request.json',dict(request=req,profile=profile,fingerprint=core.fingerprint(),
                proxy_input_tokens=count,item_sha256=digest(item),freeze_id=packet['freeze_id']))
            event=dict(judge=judge,sample_id=sid,ordinal=len(ledger)+1,started_utc=now(),
                folder=folder.relative_to(ROOT).as_posix(),request_sha256=digest(req['body']),actual_cost='Unknown')
            with (ROOT/'requests/ledger.jsonl').open('a',encoding='utf-8') as out:out.write(json.dumps(event)+'\n')
        address=urlsplit(req['url']);key=keys[judge]
        conn=http.client.HTTPSConnection(address.hostname,address.port or 443,timeout=15,context=ssl.create_default_context())
        state=dict(judge=judge,sample_id=sid,status='not_completed',started_utc=now());start=time.monotonic()
        try:
            conn.connect();conn.sock.settimeout(600)
            conn.request('POST',address.path,body=json.dumps(req['body'],ensure_ascii=False).encode('utf-8'),
                headers={'Authorization':'Bearer '+key,'Content-Type':'application/json','Accept':'application/json'})
            response=conn.getresponse();text=response.read().decode('utf-8').replace(key,'[REDACTED]')
            (folder/'response.txt').write_text(text,encoding='utf-8');state['http_status']=response.status
            if response.status!=200:
                state['status']='http_error'
                if response.status in (401,403,429):stop[judge].set()
            else:
                parsed=core.parse_current(profile,json.loads(text),item)
                core.write(folder/'parsed.json',parsed);state.update(status='valid',usage=parsed['usage'],response_model=parsed['response_model'])
        except (OSError,http.client.HTTPException,ValueError,KeyError,TypeError) as exc:
            state.update(status='failed',error_type=type(exc).__name__,reason=str(exc).replace(key,'[REDACTED]')[:500])
        finally:conn.close()
        state.update(completed_utc=now(),seconds=time.monotonic()-start);core.write(folder/'status.json',state)
        print(json.dumps(state),flush=True)
    ROOT.mkdir(parents=True,exist_ok=True)
    with exclusive_lock(ROOT/'execution.lock'):
        # Dedicated pools keep the two judges independent and bound each endpoint lane.
        with ThreadPoolExecutor(max_workers=2) as pool:
            def lane(judge):
                with ThreadPoolExecutor(max_workers=max(1,min(workers,8))) as workers_pool:
                    list(workers_pool.map(worker,[j for j in jobs if j[0]==judge]))
            list(pool.map(lane,JUDGES))
    labels,failures=collect(packet)
    core.write(ROOT/'status.json',dict(updated_utc=now(),valid={j:len(v) for j,v in labels.items()},
        failed_attempts=len(failures),original_audit_passed=False,operational_authorized=True,test160_started=False))


def answer_metrics(item,record):
    if record is not None:return joint_metrics(record,[c['criterion_id'] for c in item['criteria']],item['conditional'],item['generation_failed'])
    return calculate([None]*len(item['criteria']),None,None if item['conditional'] else 'not_applicable',item['conditional'],item['generation_failed'])
