"""Bounded, synthetic 8B service capacity measurements; never reads QA/Gold."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import argparse,json,time,statistics
from models import Client,load_model,payload,public_deployment,encoded,EXPERIMENT

PROMPT='这是接口吞吐量测试，不是知识问答题。请依次输出1到80这80个整数，用逗号分隔，不解释。'

def measure(model,levels):
    if model not in ('qwen3-8b','llama3.1-8b'):raise ValueError('Only the two 8B services are authorized for capacity measurement')
    root=EXPERIMENT/'capacity'/model;root.mkdir(parents=True,exist_ok=True)
    if (root/'summary.json').exists():raise ValueError('Existing measurement must be reviewed before repeating calls')
    rows=[];declines=0;best=0
    for level in levels:
        d=load_model(model,concurrency=level);client=Client(d,timeout=120)
        body=payload(d,[dict(role='user',content=PROMPT)],256)
        count=max(4,level*2)
        folder=root/('concurrency_'+str(level));folder.mkdir(exist_ok=False)
        def one(i):return client.complete(body,folder/(str(i).zfill(3)+'.json'))
        start=time.monotonic()
        with ThreadPoolExecutor(max_workers=level) as pool:results=list(pool.map(one,range(count)))
        seconds=time.monotonic()-start
        good=[x for x in results if x['status']=='response']
        tokens=sum(x.get('raw_response',{}).get('usage',{}).get('completion_tokens',0) for x in good)
        rate=tokens/seconds if seconds else 0
        row=dict(concurrency=level,requests=count,successful=len(good),failed=count-len(good),seconds=seconds,
                 completion_tokens=tokens,output_tokens_per_second=rate,responses_per_second=len(good)/seconds,
                 median_request_seconds=statistics.median(x['seconds'] for x in results),p95_request_seconds=sorted(x['seconds'] for x in results)[min(count-1,int(count*.95))])
        rows.append(row)
        print(json.dumps(dict(model=model,**row)),flush=True)
        if not good or any(x['status']=='model_identity_mismatch' for x in results):break
        if len(good)!=count:break
        if rate>best*1.03:best=rate;declines=0
        else:declines+=1
        if declines>=2:break
    valid=[r for r in rows if r['failed']==0 and r['completion_tokens']>0]
    selected=max(valid,key=lambda r:(r['output_tokens_per_second'],-r['concurrency'])) if valid else None
    summary=dict(status='measured' if selected else 'unavailable',**public_deployment(load_model(model)),
                 synthetic_only=True,formal_questions_used=0,formal_experiment_started=False,levels=rows,
                 recommended_concurrency=selected['concurrency'] if selected else None,
                 scope='Fastest error-free tested tier for synthetic traffic; not an absolute maximum or a formal-answer throughput guarantee.')
    (root/'summary.json').write_bytes(encoded(summary))
    return summary

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--levels',default='1,2,4,8,16,32,64');a=p.parse_args()
    levels=[int(v) for v in a.levels.split(',')]
    if not levels or min(levels)<1 or max(levels)>64:raise ValueError('Bounded concurrency tiers required')
    with ThreadPoolExecutor(max_workers=2) as pool:
        reports=list(pool.map(lambda model:measure(model,levels),('qwen3-8b','llama3.1-8b')))
    print(json.dumps({r['logical_model']:dict(status=r['status'],recommended_concurrency=r['recommended_concurrency']) for r in reports}),flush=True)
