"""Build/cache source-grounded global locator cards using the authorized official DeepSeek API."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import fcntl
import json
from pathlib import Path
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

import global_graph as g

ENDPOINT='https://api.deepseek.com/chat/completions'


def extract(unit, plan, key, prompt, retries=4):
    messages=[{'role':'system','content':prompt},{'role':'user','content':g.encoded(
        {'unit':unit['id'],'scope':unit['scope'],'case':unit['case'],'sources':unit['sources']})}]
    body={'model':plan['extraction']['model'],'thinking':{'type':'disabled'},'temperature':0,
          'max_tokens':6000,'response_format':{'type':'json_object'},'messages':messages}
    events=[]
    for attempt in range(1,retries+1):
        start=time.monotonic()
        try:
            request=Request(ENDPOINT,data=json.dumps(body).encode(),headers={'Authorization':'Bearer '+key,'Content-Type':'application/json'})
            with urlopen(request,timeout=90) as response:data=json.load(response)
            choice=data['choices'][0]
            payload=json.loads(choice['message']['content'])
            if choice.get('finish_reason')=='length':raise ValueError('truncated extraction JSON')
            if not isinstance(payload,dict) or not isinstance(payload.get('cards'),list):raise ValueError('invalid extraction shape')
            events.append({'attempt':attempt,'status':'ok','seconds':time.monotonic()-start})
            return {'status':'ok','unit':unit['id'],'cache_key':unit['cache_key'],'payload':payload,
                    'model':data.get('model'),'usage':data.get('usage'),'events':events,
                    'input_characters':sum(len(m['content']) for m in messages)}
        except (HTTPError,URLError,TimeoutError,OSError,ValueError,KeyError,IndexError) as exc:
            events.append({'attempt':attempt,'status':'error','type':type(exc).__name__,
                           'http_status':getattr(exc,'code',None),'seconds':time.monotonic()-start})
            if isinstance(exc,HTTPError) and exc.code in (401,402,403):break
            time.sleep(min(attempt,3))
    return {'status':'error','unit':unit['id'],'cache_key':unit['cache_key'],'events':events}


def run(args):
    plan=g.make_plan(model=args.model);run_dir=args.run_dir;run_dir.mkdir(parents=True,exist_ok=True)
    g.write(run_dir/'build-plan.json',plan)
    g.write(run_dir/'build-config.json',{'endpoint':ENDPOINT,'extraction':plan['extraction'],'workers':args.workers,
                                       'unit_count':len(plan['units']),'fresh_model_call_limit':len(plan['units']),
                                       'scope':'public bundled manual and tutorial source text only; no evaluation annotations'})
    if args.prepare:
        print(g.encoded({'units':len(plan['units']),'manual_units':sum(u['scope']=='manual' for u in plan['units']),
                         'tutorial_units':sum(u['scope']=='tutorial' for u in plan['units']),
                         'input_characters':sum(len(s['text']) for u in plan['units'] for s in u['sources']),
                         'resource_files':len(plan['resources'])}));return
    key=args.key_file.read_text().strip()
    if not key or any(c.isspace() for c in key):raise ValueError('bare API key expected')
    prompt=(g.ROOT/'references/global-extraction-prompt.md').read_text()
    pending=[];reused=0
    for unit in plan['units']:
        cached=g.ROOT/'semantic/global/cache'/f"{unit['cache_key']}.json"
        if cached.exists() and g.read(cached).get('status')=='ok':reused+=1
        else:pending.append(unit)
    print('source units',len(plan['units']),'cached',reused,'pending',len(pending),flush=True)
    errors=[];completed=0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        jobs={pool.submit(extract,u,plan,key,prompt):u for u in pending}
        for future in as_completed(jobs):
            unit=jobs[future];result=future.result()
            g.write(g.ROOT/'semantic/global/cache'/f"{unit['cache_key']}.json",result)
            completed+=1
            if result['status']!='ok':errors.append(unit['id'])
            if completed%10==0 or result['status']!='ok':print('processed',completed,'/',len(pending),'errors',len(errors),flush=True)
    if errors:
        g.write(run_dir/'build-errors.json',errors)
        raise RuntimeError(f'{len(errors)} extraction units failed; successful units cached; rerun to resume')
    manifest=g.assemble(plan)
    g.write(run_dir/'build-summary.json',{'counts':manifest['counts'],'snapshot':manifest['snapshot'],'reused_units':reused,
                                        'new_units':len(pending),'extraction':plan['extraction']})
    print(g.encoded(manifest['counts']),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir',type=Path,required=True)
    parser.add_argument('--key-file',type=Path)
    parser.add_argument('--workers',type=int,default=4,choices=range(1,5))
    parser.add_argument('--model',choices=['deepseek-flash'],default='deepseek-flash')
    parser.add_argument('--prepare',action='store_true')
    args=parser.parse_args()
    if not args.prepare and not args.key_file:parser.error('--key-file required')
    lockpath=g.ROOT/'semantic/global/build.lock';lockpath.parent.mkdir(parents=True,exist_ok=True)
    with lockpath.open('a') as lock:
        fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        run(args)
