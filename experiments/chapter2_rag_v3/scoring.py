"""Single current entry: prepare, score, import-human, report, verify. Calibration only."""
import runtime_layout as layout
import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
import hashlib
import http.client
import json
import os
from pathlib import Path
import ssl
import statistics
import threading
import time
from urllib.parse import urlsplit

from central_execution import DEFAULT_RUN, PROJECT, Registry, now
from judge_contract import RULES, VERSION, schema, validate, calculate, joint_metrics
from judge_api_adapter import build, parse, digest, usage
from judge_statistics import ordinal_agreement, cluster_intervals, metric_error, dual_eas

HERE = Path(__file__).parent
ROOT = DEFAULT_RUN/'evaluation/judges'
OLD = layout.asset('calibration_execution')
HUMAN = layout.asset('calibration_source')/'judges/human'
PREVIOUS = layout.asset('human')/'original_submission'
JUDGES = ('gpt_sol', 'deepseek_flash')
METRICS = ('arith', 'geo')
LOCK = threading.Lock()


def longpath(p):
    p=layout.resolve(p).resolve()
    return Path('\\\\?\\'+str(p)) if os.name=='nt' and not str(p).startswith('\\\\?\\') else p
def read(p): return json.loads(longpath(p).read_text(encoding='utf-8-sig'))
def sha(p): return hashlib.sha256(longpath(p).read_bytes()).hexdigest()
def rows(p): return [json.loads(s) for s in longpath(p).read_text(encoding='utf-8-sig').splitlines() if s.strip()] if longpath(p).exists() else []


def write(p, obj):
    p = Path(p); p.parent.mkdir(parents=True, exist_ok=True)
    temp = p.with_name(p.name+'.tmp')
    temp.write_text(json.dumps(obj, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    os.replace(temp, p)


def jsonlines(p, records):
    p = Path(p); p.parent.mkdir(parents=True, exist_ok=True)
    temp = p.with_name(p.name+'.tmp')
    temp.write_text(''.join(json.dumps(r, ensure_ascii=False)+'\n' for r in records), encoding='utf-8')
    os.replace(temp, p)


def prompt():
    return (HERE/'judge_prompt.txt').read_text(encoding='utf-8')+'\n统一评分定义：\n'+json.dumps(RULES, ensure_ascii=False)


def fingerprint():
    return {p.name:sha(p) for p in (HERE/'judge_contract.py', HERE/'scoring_rules.json', HERE/'judge_prompt.txt',
                                   HERE/'judge_api_adapter.py', PROJECT/'config/llm/judging.yaml')}


def protect():
    """Hash-only checks: never parse, display or export sealed audit contents."""
    p = ROOT/'protection.json'
    if p.exists(): return
    files = {}
    for folder in DEFAULT_RUN.iterdir():
        if not folder.is_dir() or folder.name in ('scoring', '00_archive'): continue
        for base,dirs,names in os.walk(longpath(folder)):
            dirs[:]=[d for d in dirs if d not in ('__pycache__','verification','isolated_browser_profile')]
            for name in names:
                f=Path(base)/name
                files[f.relative_to(longpath(DEFAULT_RUN)).as_posix()] = sha(f)
    # CAS integrity is already covered by its immutable manifests; do not duplicate the archive.
    for f in (DEFAULT_RUN/'00_archive').glob('*.json'):
        files[f.relative_to(DEFAULT_RUN).as_posix()] = sha(f)
    write(p, dict(created_utc=now(), files=files, audit_content_parsed=False, archive='existing immutable manifests'))


def prepare():
    protect()
    old_packet = HUMAN/'versions/unified_v2_20261023_v4/packet.json'
    packet = read(old_packet)
    private = read(OLD/'coverage_export/private_sample_map.json')['samples']
    ids = {s['sample_id']:s for s in private}
    config = Registry().judging
    if len(ids) != 18 or {s['batch'] for s in private} != {'calibration'} or {s['question_id'] for s in private} != set(config['calibration_question_ids']):
        raise ValueError('Only the fixed six-question 18-answer calibration set is allowed')
    cs = {r['sample_id']:r for r in rows(PREVIOUS/'human_coverage.jsonl')}
    es = {r['sample_id']:r for r in rows(PREVIOUS/'human_evidence.jsonl')}
    if set(cs) != set(ids) or set(es) != set(ids): raise ValueError('Legacy human identity mismatch')
    items = []; ui = []; source_root = HUMAN/'versions/phase2_after_coverage_20261023_v1/phase2_evidence/corpus'
    for group in packet['groups']:
        sources = [packet['sources'][k] for k in group['source_keys']]
        for source in sources:
            f = longpath(source_root/source['path'])
            if sha(f) != source['file_sha256']: raise ValueError('Frozen source changed')
            numbered = '\n'.join('%d|%s'%(i,s) for i,s in enumerate(f.read_text(encoding='utf-8-sig').splitlines(),1))
            if numbered != source['text']: raise ValueError('Frozen source text mismatch')
        criteria = [dict(criterion_id=c['criterion_id'], claim=c['claim']) for c in group['criteria']]
        for answer in group['answers']:
            sid = answer['sample_id']; s = ids[sid]
            if answer['answer_source_sha256'] != s['answer_sha256'] or group['conditional'] != s['conditional']:
                raise ValueError('Frozen answer binding mismatch')
            item = dict(schema_version=VERSION, sample_id=sid, question=group['question'], answer=answer['answer'],
                        generation_failed=answer['generation_failed'], criteria=criteria, conditional=group['conditional'], sources=sources)
            items.append(item)
            ui.append(dict(sample_id=sid, group_id=group['group_id'], label=answer['label'],
                legacy=dict(points={p['criterion_id']:p['score'] for p in cs[sid]['points']}, fact_gate=es[sid]['fact_gate'],
                            applicability_gate=es[sid]['applicability_gate'], reason=es[sid].get('reason',''))))
    if len(items) != 18 or {p['sample_id'] for p in items} != set(ids): raise ValueError('Incomplete calibration set')
    packet_id = digest(dict(items=items, rules=RULES))
    prepared = dict(schema_version=VERSION, packet_id=packet_id, fingerprints=fingerprint(),
        old_packet_sha256=sha(old_packet), private=private, items=items, ui=ui, audit_included=False, test160_included=False)
    if (ROOT/'calibration.json').exists() and read(ROOT/'calibration.json') != prepared and ((ROOT/'requests/ledger.jsonl').exists() or (ROOT/'human/scores.jsonl').exists()):
        raise ValueError('Prepared content changed: do not overwrite bound records')
    write(ROOT/'calibration.json', prepared)
    write(ROOT/'schema.json', schema())
    from human_unified import build_page
    build_page(prepared)
    report()
    print(json.dumps(dict(prepared=18, schema_version=VERSION, human_page=str(ROOT/'human/index.html'))))


def load():
    if ROOT.name=='audit':
        from scoring_review import guard_audit
        guard_audit()
        p=read(ROOT/'packet.json')
        if p['schema_version']!=VERSION or p['fingerprints']!=fingerprint():raise ValueError('Audit protocol drift')
        return p
    p = read(ROOT/'calibration.json')
    if p['schema_version'] != VERSION or p['fingerprints'] != fingerprint():
        raise ValueError('Scoring rules/prompt/config drift: existing results must not be reused')
    return p


def request_for(judge, item):
    registry = Registry(); profile = registry.judge_profile(judge)
    if judge not in JUDGES or profile['prompt_version'] != VERSION: raise ValueError('Wrong current judge profile')
    request = build(profile, item, 'joint', prompt(), schema())
    if profile['protocol'] == 'chat_completions':
        # This proxy's verified instruction route is one user message.
        request['body']['messages'] = [dict(role='user', content='\n\n'.join(m['content'] for m in request['body']['messages']))]
        fmt = registry.models[judge].get('response_format')
        if fmt: request['body']['response_format'] = fmt
    if request['body'].get('stream'): raise ValueError('Current scoring requires a nonstreaming profile')
    return registry, profile, request


def estimate(profile, request):
    from tokenizers import Tokenizer
    tok = Tokenizer.from_file(str(DEFAULT_RUN/'data/resources/tokenizers/qwen3-14b/tokenizer.json'))
    body = request['body']; messages = body.get('messages', body.get('input'))
    text = ''.join('<|im_start|>'+m['role']+'\n'+m['content']+'<|im_end|>\n' for m in messages)+'<|im_start|>assistant\n'
    n = len(tok.encode(text).ids)
    if n > profile['input_token_cap']: raise ValueError('Proxy input estimate exceeds cap')
    return n


def parse_current(profile, raw, item):
    """Enforce the owner's 32K combined limit, recording a provider's split-cap overrun.

    Some proxies ignore max_completion_tokens. A complete, structurally valid NEW
    response within 32K is still usable; never erase the original request/status.
    """
    u=usage(raw,profile['protocol'])
    if u['input_tokens']+u['output_tokens']>32768:raise ValueError('Provider exceeds 32K combined context')
    checked=dict(profile)
    checked.update(input_token_cap=max(profile['input_token_cap'],u['input_tokens']),
                   output_token_cap=max(profile['output_token_cap'],u['output_tokens']))
    result=parse(checked,raw,item,'joint')
    result['budget_observation']=dict(combined_tokens=u['input_tokens']+u['output_tokens'],combined_cap=32768,
        requested_input_cap=profile['input_token_cap'],requested_output_cap=profile['output_token_cap'],
        provider_split_cap_exceeded=u['input_tokens']>profile['input_token_cap'] or u['output_tokens']>profile['output_token_cap'])
    return result


def attempt(judge, item, execute=False):
    prepared = load()
    if item not in prepared['items']: raise PermissionError('Outside prepared calibration')
    registry, profile, req = request_for(judge, item)
    count = estimate(profile, req)
    if not execute: return dict(judge=judge, sample_id=item['sample_id'], proxy_input_tokens=count, status='dry_run')
    if prepared.get('batch')=='audit':
        from scoring_review import guard_audit
        guard_audit(require_human=True)
        cfg=dict(answers=12,max_attempts_per_answer=1,max_physical_requests=24,read_timeout_seconds=600)
    else:
        cfg = registry.judging['five_level_calibration']
        if cfg['audit_released'] or cfg['test160_authorized'] or cfg['answers'] != 18: raise PermissionError('Invalid calibration scope')
    if registry.judging['calibration_question_ids'] != sorted(registry.judging['calibration_question_ids']):
        raise ValueError('Unexpected calibration identity order')
    key = registry.private_key(judge)
    with LOCK:
        ledger = rows(ROOT/'requests/ledger.jsonl')
        previous = [x for x in ledger if x['judge']==judge and x['sample_id']==item['sample_id']]
        if len(previous) >= cfg['max_attempts_per_answer'] or len(ledger) >= cfg['max_physical_requests']:
            raise PermissionError('Calibration request quota exhausted')
        folder = ROOT/'requests'/judge/item['sample_id']/('attempt_'+str(len(previous)+1))
        folder.mkdir(parents=True, exist_ok=False)
        event = dict(judge=judge, sample_id=item['sample_id'], ordinal=len(ledger)+1, started_utc=now(),
                     folder=folder.relative_to(ROOT).as_posix(), request_sha256=digest(req['body']), actual_cost='Unknown')
        write(folder/'request.json', dict(request=req, profile=profile, fingerprint=fingerprint(), proxy_input_tokens=count))
        jsonlines(ROOT/'requests/ledger.jsonl', ledger+[event])
    address = urlsplit(req['url']); conn = http.client.HTTPSConnection(address.hostname,address.port or 443,timeout=15,context=ssl.create_default_context())
    state = dict(judge=judge, sample_id=item['sample_id'], status='not_completed', started_utc=now()); start=time.monotonic()
    try:
        conn.connect(); conn.sock.settimeout(cfg['read_timeout_seconds'])
        conn.request('POST', address.path, body=json.dumps(req['body'],ensure_ascii=False).encode('utf-8'),
                     headers={'Authorization':'Bearer '+key, 'Content-Type':'application/json', 'Accept':'application/json'})
        response=conn.getresponse(); text=response.read().decode('utf-8').replace(key,'[REDACTED]')
        (folder/'response.txt').write_text(text,encoding='utf-8'); state['http_status']=response.status
        if response.status != 200:
            state['status']='http_error'
        else:
            raw=json.loads(text); parsed=parse_current(profile,raw,item)
            write(folder/'parsed.json',parsed); state.update(status='valid',usage=parsed['usage'],response_model=parsed['response_model'])
    except (OSError, http.client.HTTPException, ValueError, KeyError, TypeError) as exc:
        state.update(status='failed',error_type=type(exc).__name__,reason=str(exc).replace(key,'[REDACTED]')[:500])
    finally: conn.close()
    state.update(completed_utc=now(),seconds=time.monotonic()-start); write(folder/'status.json',state)
    print(json.dumps(state),flush=True)
    return state


def score(execute=False):
    p=load(); jobs=[]
    for judge in JUDGES:
        for item in p['items']:
            if (ROOT/'requests'/judge/item['sample_id']).exists(): continue
            jobs.append((judge,item))
    if not execute:
        checks=[attempt(j,i) for j,i in jobs]; write(ROOT/'verification/request_build.json',checks)
        print(json.dumps(dict(requests=len(checks),max_proxy_input_tokens=max((x['proxy_input_tokens'] for x in checks),default=0),sent=0))); return
    from central_execution import exclusive_lock
    with exclusive_lock(ROOT/'execution.lock'):
        # Two workers total, preserving independent requests and no cross-judge grades.
        def worker(judge):
            for j,item in jobs:
                if j!=judge:continue
                state=attempt(j,item,execute=True)
                if state['status']!='valid':break  # Stop this judge on a transport/contract failure.
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(worker,JUDGES))
    report()


def verify_human_binding(p, data):
    """Recover anonymous IDs from sealed metadata; open calibration answers only.

    The browser export binds IDs/hashes through packet_id rather than repeating
    private question IDs or raw answer hashes in the visible scoring interface.
    """
    if digest(dict(items=p['items'],rules=RULES)) != p['packet_id']:
        raise ValueError('Calibration packet digest mismatch')
    manifest_path=DEFAULT_RUN/'experiments/agentic/reused_inputs/sampling_plan.answers_sealed_v1.json'
    manifest=read(manifest_path); manifest_hash=sha(manifest_path)
    frozen={'S'+hashlib.sha256((manifest_hash+'|'+s['sample_key']).encode()).hexdigest()[:16]:s for s in manifest['samples']}
    expected={i['sample_id']:i for i in p['items']};private={s['sample_id']:s for s in p['private']}
    # No audit answer or audit score values are inspected. Foreign IDs are rejected
    # before the import can replace any canonical calibration records.
    batch=p.get('batch','calibration')
    if batch not in ('calibration','audit'):raise ValueError('Unknown human scoring batch')
    if batch=='calibration' and any(sid in frozen and frozen[sid]['batch']=='audit' for sid in data.get('drafts',{})):
        raise ValueError('Sealed audit IDs in human export: keep separate from calibration')
    if set(expected)!=set(private) or set(expected)!={sid for sid,s in frozen.items() if s['batch']==batch}:
        raise ValueError('Calibration identity set differs from frozen sampling')
    bindings=[]
    for sid,item in expected.items():
        original=frozen[sid];reference=private[sid]
        if any(reference[k]!=original[k] for k in ('question_id','method_id','generator_id','batch','answer_sha256')):
            raise ValueError('Frozen question/answer identity mismatch: '+sid)
        if reference['batch']!=batch or reference['conditional']!=item['conditional']:
            raise ValueError('Outside calibration or applicability mismatch: '+sid)
        answer_path=original['answer_path']
        if sha(answer_path)!=original['answer_sha256'] or read(answer_path)['answer']!=item['answer']:
            raise ValueError('Original answer hash/text mismatch: '+sid)
        bindings.append(dict(sample_id=sid,question_id=reference['question_id'],method_id=reference['method_id'],
            raw_answer_sha256=reference['answer_sha256'],answer_text_sha256=hashlib.sha256(item['answer'].encode()).hexdigest()))
    return bindings


def import_human(path):
    p=load(); data=read(path)
    if data.get('schema_version')!=VERSION or data.get('packet_id')!=p['packet_id']:
        raise ValueError('Wrong/legacy human export: use the current page')
    if not isinstance(data.get('drafts'),dict):raise ValueError('Human drafts must be an ID-indexed object')
    bindings=verify_human_binding(p,data)
    expected={s['sample_id']:s for s in p['items']}
    if not isinstance(data.get('drafts'),dict) or set(data['drafts'])!=set(expected): raise ValueError('Human sample set mismatch')
    records=[]
    for sid,d in data['drafts'].items():
        item=expected[sid]; criteria=[c['criterion_id'] for c in item['criteria']]
        fields=criteria+['F']+(['A'] if item['conditional'] else [])
        if set(d.get('values',{})) != set(fields) or set(d.get('confirmed',{})) != set(fields): raise ValueError('Human fields mismatch')
        if any(type(d['confirmed'][k]) is not bool for k in fields): raise ValueError('Invalid human confirmation')
        for k,v in d['values'].items():
            if v is not None and not (type(v) in (int,float) and v in RULES['levels'] or v=='unknown'):raise ValueError('Invalid draft score')
        if not isinstance(d.get('reason',''),str):raise ValueError('Invalid human note')
        if any(not d['confirmed'][k] or d['values'][k] is None for k in fields): continue
        record=dict(schema_version=VERSION,sample_id=sid,judge_id='human',judge_version=VERSION,status='complete',
                    points=[dict(criterion_id=k,score=d['values'][k]) for k in criteria],fact_gate=d['values']['F'],
                    applicability_gate=d['values']['A'] if item['conditional'] else 'not_applicable',reason=d.get('reason',''))
        validate(record,'joint',criteria,item['conditional']); records.append(record)
    # Preserve exact submitted bytes as evidence; only canonical derived files are replaced.
    archive=ROOT/'human/submissions'/(sha(path)+'.json')
    archive.parent.mkdir(parents=True,exist_ok=True)
    if not archive.exists():archive.write_bytes(Path(path).read_bytes())
    write(ROOT/'human/draft.json',data); jsonlines(ROOT/'human/scores.jsonl',records)
    write(ROOT/'human/import_validation.json',dict(source_sha256=sha(path),packet_id=p['packet_id'],
        confirmed_answers=len(records),expected_answers=len(expected),question_and_answer_bindings=bindings,
        batch=p.get('batch','calibration'),audit_records_found=len(records) if p.get('batch')=='audit' else 0,
        audit_answer_content_read=p.get('batch')=='audit',original_submission_modified=False))
    from human_unified import build_page
    build_page(p); report()
    print(json.dumps(dict(confirmed_answers=len(records),pending_answers=len(expected)-len(records))))


def collect(judge, items):
    if judge=='human': records=rows(ROOT/'human/scores.jsonl')
    else:
        records=[]
        for item in items:
            valid=[]
            for f in sorted((ROOT/'requests'/judge/item['sample_id']).glob('attempt_*/parsed.json')):
                request=read(f.parent/'request.json')
                if request['fingerprint']!=fingerprint():raise ValueError('Stale scoring request')
                _,profile,current=request_for(judge,item)
                if not layout.judge_request_matches(request,profile,current):raise ValueError('Stored judge request differs from current protocol')
                record=read(f)['record']
                if parse_current(profile,read(f.parent/'response.txt'),item)['record']!=record:
                    raise ValueError('Parsed judge label differs from raw response')
                valid.append(record)
            if valid:records.append(valid[0])  # First valid response, never score-based selection.
    result={}
    byid={i['sample_id']:i for i in items}
    for r in records:
        if r['sample_id'] in result or r['sample_id'] not in byid or r['judge_id']!=judge:raise ValueError('Duplicate/foreign scoring record')
        i=byid[r['sample_id']];validate(r,'joint',[c['criterion_id'] for c in i['criteria']],i['conditional'])
        result[r['sample_id']]=r
    if judge!='human':jsonlines(ROOT/'results'/(judge+'.jsonl'),list(result.values()))
    return result


def summarize(metrics):
    result=dict(expected_answers=len(metrics))
    for name in METRICS:
        key='EAS_'+name; b='eas_'+name+'_bounds'
        result[key]=statistics.mean(m[key] for m in metrics) if metrics and all(m[key] is not None for m in metrics) else None
        result[b]=[statistics.mean(m[b][j] for m in metrics) for j in (0,1)]
        result[key+'_known_answers']=sum(m[key] is not None for m in metrics)
    if all('Strict' in m for m in metrics):
        result['Strict']=statistics.mean(m['Strict'] for m in metrics) if all(m['Strict'] is not None for m in metrics) else None
        result['strict_bounds']=[statistics.mean(m['strict_bounds'][j] for m in metrics) for j in (0,1)]
    return result


def draft_metrics(item,draft):
    """Confirmed fields narrow bounds even before the whole Human answer is complete."""
    def value(k):
        return draft.get('values',{}).get(k) if draft.get('confirmed',{}).get(k) is True else None
    return calculate([value(c['criterion_id']) for c in item['criteria']],value('F'),
        value('A') if item['conditional'] else 'not_applicable',item['conditional'],item['generation_failed'])


def pair_statistics(left, right, items, private):
    pairs={k:[] for k in ('K','F','A')};deltas={n:[] for n in METRICS};missing=[]
    for i in items:
        sid=i['sample_id'];l=left.get(sid);r=right.get(sid)
        if not l or not r:missing.append(sid);continue
        lp={p['criterion_id']:p['score'] for p in l['points']};rp={p['criterion_id']:p['score'] for p in r['points']}
        pairs['K'].extend((lp[k],rp[k]) for k in lp)
        pairs['F'].append((l['fact_gate'],r['fact_gate']))
        if i['conditional']:pairs['A'].append((l['applicability_gate'],r['applicability_gate']))
        lm=joint_metrics(l,lp,i['conditional'],i['generation_failed']);rm=joint_metrics(r,rp,i['conditional'],i['generation_failed'])
        for n in METRICS:
            k='EAS_'+n
            if lm[k] is not None and rm[k] is not None:deltas[n].append((private[sid]['question_id'],rm[k]-lm[k]))
    result=dict(expected_answers=len(items),paired_answers=len(items)-len(missing),missing_samples=missing,
                **{k:ordinal_agreement(v) for k,v in pairs.items()})
    for n,ds in deltas.items():
        result['EAS_'+n]=metric_error(ds)
    return result


def disagreement_records(labels, allmetrics, items, private):
    """Observed adjacent/category differences, without inferring who is correct."""
    output=[]
    for item in items:
        sid=item['sample_id'];human=labels['human'].get(sid)
        if not human:continue
        hvalues={p['criterion_id']:p['score'] for p in human['points']}
        hvalues['F']=human['fact_gate']
        if item['conditional']:hvalues['A']=human['applicability_gate']
        differences=[]
        for judge in JUDGES:
            record=labels[judge].get(sid)
            if not record:continue
            values={p['criterion_id']:p['score'] for p in record['points']}
            values['F']=record['fact_gate']
            if item['conditional']:values['A']=record['applicability_gate']
            for field,score in hvalues.items():
                if score!=values[field]:
                    point=next((p for p in record['points'] if p['criterion_id']==field),{})
                    differences.append(dict(field=field,human=score,judge=judge,judge_score=values[field],
                        criterion_claim=next((c['claim'] for c in item['criteria'] if c['criterion_id']==field),None),
                        point_note=point.get('reason',''),answer_note=record.get('reason','')))
        if differences:
            output.append(dict(sample_id=sid,question_id=private[sid]['question_id'],method_id=private[sid]['method_id'],
                differences=differences,metrics={j:allmetrics[j][sid] for j in labels},
                human_current_note=human.get('reason',''),interpretation='Observed labels only; no automatic adjudication'))
    return output


def method_statistics(allmetrics, dual, private):
    from itertools import combinations
    results=[]
    for model in sorted({s['generator_id'] for s in private.values()}):
        by_method={}
        for sid,s in private.items():
            if s['generator_id']==model:by_method.setdefault(s['method_id'],{})[s['question_id']]=sid
        for left,right in combinations(sorted(by_method),2):
            qs=sorted(set(by_method[left])|set(by_method[right]))
            for judge,mm in dict(allmetrics,dual_mean=dual).items():
                for n in METRICS:
                    key='EAS_'+n;b='eas_'+n+'_bounds';ds=[];bs=[]
                    for q in qs:
                        l=mm.get(by_method[left].get(q));r=mm.get(by_method[right].get(q))
                        if l is None or r is None:bs.append([-100,100]);continue
                        bs.append([r[b][0]-l[b][1],r[b][1]-l[b][0]])
                        if l[key] is not None and r[key] is not None:ds.append((q,r[key]-l[key]))
                    results.append(dict(model=model,left_method=left,right_method=right,judge=judge,metric=key,
                        expected_questions=len(qs),known_pairs=len(ds),mean_difference_right_minus_left=statistics.mean(d for _,d in ds) if len(ds)==len(qs) else None,
                        difference_bounds=[statistics.mean(b[j] for b in bs) for j in (0,1)],
                        uncertainty=cluster_intervals(ds),interpretation='Dev calibration descriptive only; no confirmatory tests or method selection'))
    return results


def report():
    p=load();items=p['items'];labels={j:collect(j,items) for j in ('human',)+JUDGES}; allmetrics={}; records=[]
    batch=p.get('batch','calibration');question_count=len({s['question_id'] for s in p['private']})
    drafts=read(ROOT/'human/draft.json')['drafts'] if (ROOT/'human/draft.json').exists() else {}
    for judge in labels:
        allmetrics[judge]={}
        for i in items:
            sid=i['sample_id']; criteria=[c['criterion_id'] for c in i['criteria']]; r=labels[judge].get(sid)
            m=joint_metrics(r,criteria,i['conditional'],i['generation_failed']) if r else draft_metrics(i,drafts.get(sid,{}) if judge=='human' else {})
            allmetrics[judge][sid]=m; records.append(dict(judge=judge,sample_id=sid,**m))
    dual={}
    for i in items:
        ms=[allmetrics[j][i['sample_id']] for j in JUDGES]
        dual[i['sample_id']]=dual_eas(ms)
    private={s['sample_id']:s for s in p['private']}
    agreement={j:pair_statistics(labels['human'],labels[j],items,private) for j in JUDGES}
    dual_agreement={}
    for name in METRICS:
        key='EAS_'+name
        pairs=[(private[sid]['question_id'],dual[sid][key]-allmetrics['human'][sid][key]) for sid in dual
               if dual[sid][key] is not None and allmetrics['human'][sid][key] is not None]
        dual_agreement[key]=metric_error(pairs)
    summaries={j:dict(summarize(list(mm.values())),scored_answers=len(labels[j])) for j,mm in allmetrics.items()}
    summaries['dual_mean']=summarize(list(dual.values()))
    by_method_model={}
    for sid,s in private.items():
        group=s['generator_id']+' / '+s['method_id']
        by_method_model.setdefault(group,[]).append(sid)
    grouped={group:{j:summarize([mm[sid] for sid in sids]) for j,mm in dict(allmetrics,dual_mean=dual).items()} for group,sids in by_method_model.items()}
    workflow_path=DEFAULT_RUN/'evaluation/judges/protocol.json'
    workflow=read(workflow_path) if workflow_path.exists() else {}
    output=dict(schema_version=VERSION,created_utc=now(),packet_id=p['packet_id'],summaries=summaries,by_method_model=grouped,agreement=agreement,
        human_reference=read(ROOT/'human/import_validation.json') if (ROOT/'human/import_validation.json').exists() else None,
        judge_agreement=pair_statistics(labels['gpt_sol'],labels['deepseek_flash'],items,private),
        dual_mean_vs_human=dual_agreement,
        statistics_definition=dict(K='per necessary point; unweighted',F='per answer',A='conditional answers only',
            weighted_kappa='quadratic five-level ordinal weights',dimension_error_units='0..1',EAS_error_units='0..100 points',
            bias='right minus left; judge minus Human in human-reference comparisons',
            uncertainty='question-cluster diagnostic bootstrap, not independent-answer inference'),
        method_comparisons=method_statistics(allmetrics,dual,private),
        model_comparisons=dict(status='only_qwen3-14b_'+batch+'_observed',qwen3_8b='pending_new_generation_and_five_level_scoring',metrics=['EAS_arith','EAS_geo']),
        batch=batch,human_reconfirmation_pending=len(items)-len(labels['human']),
        calibration_accepted_by_owner=workflow.get('calibration_accepted_by_owner',False),
        reliability_accepted=workflow.get('status')=='final_frozen',
        audit_sealed=batch!='audit' and not (DEFAULT_RUN/'evaluation/judges/audit/release.json').exists(),test160_started=False,
        historical_scores='legacy_only_invalid_for_current_metric',records=records,dual_per_answer=dual)
    write(ROOT/'results/summary.json',output)
    differences=disagreement_records(labels,allmetrics,items,private)
    write(ROOT/'results/disagreements.json',dict(schema_version=VERSION,packet_id=p['packet_id'],
        answers_with_differences=len(differences),records=differences,original_labels_modified=False))
    f=ROOT/'results/answers.csv';f.parent.mkdir(parents=True,exist_ok=True)
    with f.open('w',encoding='utf-8-sig',newline='') as stream:
        writer=csv.writer(stream);writer.writerow(['sample_id','model','method','judge','K','F','A','EAS_arith','EAS_arith_lower','EAS_arith_upper','EAS_geo','EAS_geo_lower','EAS_geo_upper','Strict'])
        for r in records:
            s=private[r['sample_id']];writer.writerow([r['sample_id'],s['generator_id'],s['method_id'],r['judge'],r['K'],r['F'],r['A'],r['EAS_arith'],*r['eas_arith_bounds'],r['EAS_geo'],*r['eas_geo_bounds'],r['Strict']])
        for sid,m in dual.items():
            s=private[sid];writer.writerow([sid,s['generator_id'],s['method_id'],'dual_mean','','','',m['EAS_arith'],*m['eas_arith_bounds'],m['EAS_geo'],*m['eas_geo_bounds'],''])
    # One self-contained results dashboard, including unknown intervals and original denominators.
    from html import escape
    def number(v):return 'Unknown' if v is None else '%.3f'%v
    agreement_rows=''
    for judge,table in agreement.items():
        for dimension in ('K','F','A'):
            a=table[dimension]
            agreement_rows+='<tr><td>'+judge+'</td><td>'+dimension+'</td><td>'+str(a['n'])+'</td><td>'+number(100*a['exact'] if a['exact'] is not None else None)+'%</td><td>'+number(a['quadratic_kappa'])+'</td><td>'+number(a['mae'])+'</td><td>'+number(a['bias_right_minus_left'])+'</td></tr>'
    error_rows=''
    for judge,table in dict(agreement,dual_mean=dual_agreement).items():
        for name in METRICS:
            key='EAS_'+name;a=table[key]
            error_rows+='<tr><td>'+judge+'</td><td>'+key+'</td><td>'+str(a['identified_pairs'])+'</td><td>'+number(a['mae'])+'</td><td>'+number(a['bias_right_minus_left'])+'</td></tr>'
    body=''
    for group,table in [('全部校准回答',summaries)]+list(grouped.items()):
        for j,s in table.items():
            for name in METRICS:
                key='EAS_'+name;value='Unknown' if s[key] is None else '%.2f'%s[key];lo,hi=s['eas_'+name+'_bounds']
                strict='—' if 'Strict' not in s else 'Unknown' if s['Strict'] is None else '%.1f%%'%(100*s['Strict'])
                body+='<tr data-metric="'+key+'"><td>'+escape(group)+'</td><td>'+escape(j)+'</td><td>'+key+'</td><td>'+str(s[key+'_known_answers'])+'/'+str(s['expected_answers'])+'</td><td>'+value+'</td><td>[%.2f, %.2f]</td><td><meter min="0" max="100" value="%s"></meter></td><td>'%(lo,hi,lo)+strict+'</td></tr>'
    html='''<!doctype html><meta charset="utf-8"><title>五档双指标评分结果</title>
<style>body{font:16px system-ui;max-width:1300px;margin:40px auto;padding:0 16px}td,th{padding:8px;text-align:left}meter{width:160px}</style>
<h1>五档评分 · EAS_arith 与 EAS_geo</h1>
<p>固定%d题%d答；Unknown保留上下界。人工完整评分：%d/%d。批次：%s；Test160未运行。</p>
<p><a href="../human/index.html">人工联合评分</a> · <a href="summary.json">完整统计</a> · <a href="answers.csv">逐答CSV</a> · <a href="disagreements.json">逐项分歧</a> · <a href="calibration_review.md">校准验收与原文核查</a></p>
<h2>相对人工的五档一致性</h2>
<p>K按必要点，F按回答，A仅条件回答。MAE/Bias单位0–1；Bias为裁判减人工。加权Kappa采用二次权重，退化分布需单独解释；N/A不等于零分。</p>
<table><tr><th>裁判</th><th>维度</th><th>配对数</th><th>完全一致率</th><th>加权Kappa</th><th>MAE</th><th>Bias</th></tr>%s</table>
<h2>相对人工的综合得分误差</h2>
<p>单位为0–100分；按题聚类的描述性区间见完整统计，不作为可靠性认证或方法显著性结论。</p>
<table><tr><th>裁判</th><th>指标</th><th>配对数</th><th>MAE</th><th>Bias</th></tr>%s</table>
<h2>各方法双指标</h2>
<label>显示指标 <select id="metric"><option value="">两项指标</option><option>EAS_arith</option><option>EAS_geo</option></select></label>
<table><tr><th>模型 / 方法</th><th>裁判</th><th>指标</th><th>点估计已知</th><th>均值</th><th>识别边界</th><th>下界</th><th>Strict</th></tr>%s</table>
<p>两指标基于相同K/F/A。双裁判逐指标取简单平均；缺失不替补。当前仅14B三方法校准，8B及全面Dev/Test无新结果。旧成绩不进入本表。Strict为各裁判的辅助比例，不合并为主分数。</p>
<script>document.getElementById("metric").onchange=e=>document.querySelectorAll("tr[data-metric]").forEach(r=>r.hidden=!!e.target.value&&r.dataset.metric!==e.target.value)</script>
'''%(question_count,len(items),len(labels['human']),len(items),batch,agreement_rows,error_rows,body)
    if batch=='audit':html=html.replace('href="../human/index.html"','href="../index.html"').replace('href="calibration_review.md"','href="acceptance.json"').replace('三方法校准','三方法独立审计')
    (ROOT/'results/index.html').write_text(html,encoding='utf-8')
    if batch=='audit':return output
    write(DEFAULT_RUN/'LATEST_CALIBRATION_STATUS.json',dict(schema_version=VERSION,current='scoring/README.md',results='scoring/results/summary.json',
        review='scoring/results/calibration_review.md',human='scoring/human/index.html',human_pending=output['human_reconfirmation_pending'],
        valid_judge_answers={j:len(labels[j]) for j in JUDGES},reliability_accepted=output['reliability_accepted'],
        audit_sealed=output['audit_sealed'],test160_started=False))
    return output


def verify():
    migrated=DEFAULT_RUN/'release/validation/migration_verify.py'
    if migrated.exists():
        import runpy
        return runpy.run_path(str(migrated),run_name='__main__')
    p=read(ROOT/'protection.json');changes=[name for name,h in p['files'].items() if not longpath(DEFAULT_RUN/name).exists() or sha(DEFAULT_RUN/name)!=h]
    result=dict(protected_files=len(p['files']),changed=changes,audit_content_parsed=False,history_deleted=False)
    write(ROOT/'verification/protection.json',result)
    if changes:raise ValueError('Historical evidence changed: '+str(changes[:5]))
    print(json.dumps(result))


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('command',choices=['prepare','score','import-human','report','verify','retry','review',
        'import-review','audit-prepare','audit-import-human','audit-score','audit-report','freeze'])
    ap.add_argument('--execute',action='store_true');ap.add_argument('--file',type=Path);ap.add_argument('--judge',choices=JUDGES);ap.add_argument('--sample-id')
    args=ap.parse_args()
    if args.command in ('import-review','audit-prepare','audit-import-human','audit-score','audit-report','freeze'):
        from scoring_review import import_review,prepare_audit,import_audit_human,audit_score,audit_report,finalize
        if args.command in ('import-review','audit-import-human') and not args.file:ap.error('--file required')
        actions={'import-review':lambda:import_review(args.file),'audit-prepare':prepare_audit,
            'audit-import-human':lambda:import_audit_human(args.file),'audit-score':lambda:audit_score(args.execute),
            'audit-report':audit_report,'freeze':finalize}
        print(json.dumps(actions[args.command]()))
    elif args.command=='review':
        from scoring_review import build_review
        print(json.dumps(build_review()))
    elif args.command=='prepare':prepare()
    elif args.command=='score':score(args.execute)
    elif args.command=='import-human':
        if not args.file:ap.error('--file required')
        import_human(args.file)
    elif args.command=='verify':verify()
    elif args.command=='retry':
        p=load();item=next((i for i in p['items'] if i['sample_id']==args.sample_id),None)
        if not args.judge or item is None:ap.error('calibration --judge and --sample-id required')
        if collect(args.judge,p['items']).get(item['sample_id']):raise ValueError('Valid current score already exists')
        attempt(args.judge,item,args.execute);report()
    else:report()


if __name__=='__main__': main()
