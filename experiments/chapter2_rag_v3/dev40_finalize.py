"""Dev-only bounded scoring recovery. Original requests and responses are immutable.

The frozen packet is the authority; no generation or Test request is made here.
"""
import runtime_layout as layout
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import http.client
import json
import ssl
import threading
import time
from urllib.parse import urlsplit

import single_pass_dev40 as s
import dev40_scoring as dc
import scoring as core
from central_execution import Registry, exclusive_lock
from judge_api_adapter import digest

RETRY_HTTP = {429, 500, 502, 503, 504}
MAX_NEW_ATTEMPTS = 3
WRITE_LOCK = threading.Lock()
RETRY_INVALID = False


def folders(root):
    return ([root] if (root/'request.json').exists() else []) + sorted(
        (root/'recovery').glob('attempt_*'), key=lambda p: int(p.name.split('_')[-1]))


def request(judge, item):
    _, profile, req, count = dc.request_for(judge, item)
    req['body']['max_completion_tokens' if judge == 'gpt_sol' else 'max_tokens'] = (
        8192 if judge == 'gpt_sol' else profile['output_token_cap'])
    return profile, req, count


def reconcile(root, judge, item):
    """Validate every usable saved response before deciding whether to send.

    A request without an explicit HTTP failure is unresolved, even after timeout.
    Invalid complete HTTP-200 JSON is a definite schema failure, not a success.
    """
    profile, req, _ = request(judge, item)
    if (root/'reuse.json').exists():
        reused=s.load(root/'reuse.json');source=layout.resolve(__import__('pathlib').Path(reused['source']))
        if reused.get('sha256') is None or not (root/'parsed.json').exists():
            return 'reuse_pending'
        if s.sha(source)!=reused['sha256']:
            raise ValueError('Reused score hash drift')
        original=source.parent
        visited=set()
        while (original/'reuse.json').exists():
            if str(original) in visited:raise ValueError('Cyclic score provenance')
            visited.add(str(original));link=s.load(original/'reuse.json')
            source=layout.resolve(__import__('pathlib').Path(link['source']))
            if s.sha(source)!=link['sha256']:raise ValueError('Nested reused score drift')
            original=source.parent
        resolution=s.load(original/'resolution.json') if (original/'resolution.json').exists() else {}
        actual=layout.resolve(__import__('pathlib').Path(resolution.get('source',str(original))))
        if s.load(actual/'request.json')['request']!=req:
            raise ValueError('Reused score request drift')
        parsed=core.parse_current(profile,s.load(actual/'response.txt'),item)
        if parsed['record']!=s.load(root/'parsed.json')['record']:
            raise ValueError('Reused score content drift')
        return 'valid'
    if item.get('generation_failed'):
        return 'generation_failure_zero'
    resolution = s.load(root/'resolution.json') if (root/'resolution.json').exists() else {}
    canonical_source = resolution.get('source')
    if resolution.get('status') == 'valid' and canonical_source and canonical_source != str(root):
        source = layout.resolve(__import__('pathlib').Path(canonical_source))
        if s.load(source/'request.json')['request'] != req:
            raise ValueError('Recovered request drift')
        parsed = core.parse_current(profile,s.load(source/'response.txt'),item)
        if parsed['record'] != s.load(root/'parsed.json')['record']:
            raise ValueError('Canonical recovered score drift')
        if s.sha(source/'response.txt') != resolution['response_sha256']:
            raise ValueError('Recovered raw response drift')
        return 'valid'
    valid = []
    unresolved = []
    nonretryable = []
    for folder in folders(root):
        saved = s.load(folder/'request.json')
        if saved['request'] != req:
            raise ValueError('Frozen request drift: '+str(folder))
        state = s.load(folder/'status.json') if (folder/'status.json').exists() else {}
        rawfile = folder/'response.txt'
        parsedfile = folder/'parsed.json'
        if rawfile.exists():
            try:
                raw = s.load(rawfile)
                parsed = core.parse_current(profile, raw, item)
            except (ValueError, KeyError, TypeError) as exc:
                if parsedfile.exists() and not (folder == root and canonical_source and canonical_source != str(root)):
                    raise ValueError('Saved parsed score fails raw-response validation') from exc
                reason = state.get('reason', '')
                code = state.get('http_status')
                if code in RETRY_HTTP or any(reason == 'http_'+str(c) for c in RETRY_HTTP):
                    continue
                if code == 200:
                    if RETRY_INVALID and state.get('reason') in (
                        'Duplicate/mismatched criteria','Truncated/multiple response',
                        'Unexpected or missing contract fields',
                        'Provider exceeds 32K combined context'):
                        continue
                    nonretryable.append(str(folder))
                else:
                    unresolved.append(str(folder))
            else:
                if parsedfile.exists():
                    old = s.load(parsedfile)
                    if any(parsed.get(k) != v for k, v in old.items() if k != 'budget_observation'):
                        raise ValueError('Parsed/raw score mismatch')
                else:
                    s.save(parsedfile, parsed)
                valid.append((folder, parsed))
        else:
            unresolved.append(str(folder))
    if valid:
        # Exactly one canonical score per answer/judge, even with historical attempts.
        folder, parsed = valid[0]
        if not (root/'parsed.json').exists():
            s.save(root/'parsed.json', parsed)
        s.save(root/'resolution.json', dict(status='valid', source=str(folder),
            response_sha256=s.sha(folder/'response.txt'), parsed_sha256=s.sha(folder/'parsed.json'),
            duplicate_valid_attempts=max(0,len(valid)-1), unresolved_other_attempts=unresolved))
        return 'valid'
    if unresolved:
        s.save(root/'resolution.json', dict(status='unknown_hold',
            checked_requests=[str(f) for f in folders(root)], unresolved=unresolved,
            policy='No resend without provider reconciliation; actual cost Unknown'))
        return 'unknown_hold'
    if nonretryable:
        return 'invalid_hold'
    if len(list((root/'recovery').glob('attempt_*'))) >= MAX_NEW_ATTEMPTS:
        return 'attempt_limit'
    return 'pending'


def attempt(root, judge, item, ordinal, registry):
    folder = root/'recovery'/('attempt_'+str(ordinal))
    folder.mkdir(parents=True, exist_ok=False)
    profile, req, count = request(judge, item)
    s.save(folder/'request.json', dict(request=req, profile=profile,
        request_sha256=digest(req['body']), packet_item_sha256=digest(item),
        input_token_estimate=count, protocol_sha256=s.sha(s.OUT/'protocol.json')))
    state = dict(status='unknown', judge=judge, sample_id=item['sample_id'],
        started_utc=s.now(), actual_cost='Unknown', request_sha256=digest(req['body']))
    with WRITE_LOCK:
        s.append(s.OUT/'scoring'/judge/'recovery_ledger.jsonl', dict(state, folder=str(folder)))
    key = registry.private_key(judge)
    address = urlsplit(req['url'])
    conn = http.client.HTTPSConnection(address.hostname,address.port or 443,timeout=15,
                                      context=ssl.create_default_context())
    start=time.monotonic()
    try:
        conn.connect()
        conn.sock.settimeout(600)
        conn.request('POST',address.path,body=json.dumps(req['body'],ensure_ascii=False).encode(),
            headers={'Authorization':'Bearer '+key,'Content-Type':'application/json','Accept':'application/json'})
        response=conn.getresponse()
        state['http_status']=response.status
        rawtext=response.read().decode('utf-8').replace(key,'[REDACTED]')
        (folder/'response.txt').write_text(rawtext,encoding='utf-8')
        if response.status != 200:
            state.update(status='http_error', reason='http_'+str(response.status))
        else:
            parsed=core.parse_current(profile,json.loads(rawtext),item)
            s.save(folder/'parsed.json',parsed)
            state.update(status='valid',usage=parsed['usage'],response_model=parsed['response_model'])
    except Exception as exc:
        state.update(error_type=type(exc).__name__,reason=str(exc).replace(key,'[REDACTED]')[:500])
        if state.get('http_status')==200 and (folder/'response.txt').exists():
            state['status']='invalid_response'
    finally:
        conn.close()
    state.update(completed_utc=s.now(),seconds=round(time.monotonic()-start,3))
    s.save(folder/'status.json',state)
    with WRITE_LOCK:
        s.append(s.OUT/'scoring'/judge/'recovery_events.jsonl',dict(state,folder=str(folder)))
    return state


def score(judge,workers=2,execute=False):
    dc.guard_operational()
    packet=s.load(s.OUT/'scoring/packet.json')
    expected=s.load(s.OUT/'protocol.json')['scope']['generation_sessions']
    assert packet['count']==expected and len(packet['items'])==expected
    assert packet['protocol_sha256']==s.sha(s.OUT/'protocol.json')
    rows=packet['items']
    assert len({x['item']['sample_id'] for x in rows})==expected
    registry=Registry()
    statuses={}
    pending=[]
    for row in rows:
        item=row['item'];root=s.OUT/'scoring'/judge/item['sample_id']
        state=reconcile(root,judge,item)
        statuses[item['sample_id']]=state
        if state=='pending':pending.append(item)
    s.save(s.OUT/'scoring'/judge/'recovery_preflight.json',dict(
        created_utc=s.now(),states=statuses,pending=len(pending),workers=workers,
        max_additional_attempts_per_answer=MAX_NEW_ATTEMPTS,backoff_seconds=[5,20],
        timeout_policy='unknown_hold: reconcile response/ledger, never blindly resend',
        test160=False,packet_sha256=s.sha(s.OUT/'scoring/packet.json')))
    print(json.dumps(dict(judge=judge,pending=len(pending),states={k:list(statuses.values()).count(k) for k in set(statuses.values())})),flush=True)
    if not execute:return statuses
    stop=threading.Event();counter={'http_failures':0};counter_lock=threading.Lock()
    def job(item):
        root=s.OUT/'scoring'/judge/item['sample_id']
        while not stop.is_set():
            state=reconcile(root,judge,item)
            if state!='pending':return state
            ordinal=len(list((root/'recovery').glob('attempt_*')))+1
            if ordinal>1:time.sleep([5,20][min(ordinal-2,1)])
            if stop.is_set():return 'circuit_stopped'
            result=attempt(root,judge,item,ordinal,registry)
            with counter_lock:
                counter['http_failures']=0 if result['status']=='valid' else counter['http_failures']+1
                if counter['http_failures']>=6:stop.set()
            if result['status']=='valid':return reconcile(root,judge,item)
            if result.get('http_status') not in RETRY_HTTP:return reconcile(root,judge,item)
        return 'circuit_stopped'
    with ThreadPoolExecutor(max_workers=workers) as pool:
        fs={pool.submit(job,item):item['sample_id'] for item in pending}
        for n,f in enumerate(as_completed(fs),1):
            result=f.result();statuses[fs[f]]=result
            print(json.dumps(dict(judge=judge,completed=n,pending_total=len(pending),sample_id=fs[f],status=result)),flush=True)
    s.save(s.OUT/'scoring'/judge/'recovery_summary.json',dict(completed_utc=s.now(),
        states=statuses,circuit_stopped=stop.is_set(),test160=False))
    return statuses


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('judge',choices=s.JUDGES)
    p.add_argument('--workers',type=int,default=2,choices=range(1,5))
    p.add_argument('--execute',action='store_true')
    p.add_argument('--retry-invalid',action='store_true',help='Finite recovery of explicitly invalid complete responses; no prompt change')
    p.add_argument('--output',type=__import__('pathlib').Path)
    args=p.parse_args()
    RETRY_INVALID=args.retry_invalid
    if args.output:
        output=args.output.resolve()
        if not output.is_relative_to((s.RUN/'experiments/agentic/dev40').resolve()):
            raise PermissionError('Only Dev40 supplement output permitted')
        s.OUT=output
    with exclusive_lock(s.OUT/('finalize_'+args.judge+'.lock')):
        score(args.judge,args.workers,args.execute)
