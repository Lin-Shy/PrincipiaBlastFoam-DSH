"""AI source-context review of objective candidates; never a generation input."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
from pathlib import Path

import objective_experiment as experiment

REVIEW = experiment.BASE / 'objective_review_v1'
DATA = experiment.DATA
CORPUS = experiment.BASE / 'data/resources/corpus'

def packet(question, gold):
    contexts=[]
    for ev in gold['evidence']:
        source=CORPUS/ev['path']
        if experiment.sha(source)!=ev['sha256']:
            raise ValueError('source hash mismatch: '+ev['path'])
        lines=source.read_text(encoding='utf-8').splitlines()
        start=max(1,ev['start']-24); end=min(len(lines),ev['end']+24)
        contexts.append(dict(path=ev['path'],anchor=ev['start'],start=start,
                             text='\n'.join(f'{i}: {lines[i-1]}' for i in range(start,end+1))))
    return dict(question=question,expected_answer=gold['answer'],aliases=gold['aliases'],sources=contexts)

def check():
    qs=experiment.read(DATA/'model/questions.json')
    annotations=experiment.read(DATA/'scoring/annotations.json')
    gold={g['id']:g for g in annotations}
    if len(qs)!=172 or len(gold)!=172 or len({q['id'] for q in qs})!=172 or {q['id'] for q in qs}!=set(gold):
        raise ValueError('Frozen question/annotation identities mismatch')
    experiment.verify()
    total_chars=0;max_chars=0
    for q in qs:
        item=packet(q,gold[q['id']]); size=len(json.dumps(item,ensure_ascii=False)); total_chars+=size;max_chars=max(max_chars,size)
    deployment=experiment.supercomputer_deployment()
    if deployment['max_concurrency']<1:raise ValueError('Invalid concurrency')
    print(json.dumps(dict(status='passed',items=len(qs),maximum_packet_characters=max_chars,total_packet_characters=total_chars,model=deployment['api_model_id'],network_requests=0)),flush=True)

def run(limit=None):
    check()
    qs=experiment.read(DATA/'model/questions.json')
    gold={g['id']:g for g in experiment.read(DATA/'scoring/annotations.json')}
    binding=dict(questions_sha256=experiment.sha(DATA/'model/questions.json'),
                 annotations_sha256=experiment.sha(DATA/'scoring/annotations.json'),
                 code_sha256=experiment.sha(Path(__file__)),
                 deployment=experiment.supercomputer_deployment(),
                 method='AI source-context review; not human review; no score-based selection')
    manifest=REVIEW/'manifest.json'
    if manifest.exists():
        if experiment.read(manifest)!=binding: raise ValueError('review inputs changed')
    else: experiment.save(manifest,binding)
    prompt=('你是专业题目审校员。只依据所给的原始资料上下文判断题目、标准答案和选项。'
            '判断来源是否足以支持答案、问题条件是否充分、单选是否恰有一个正确选项。'
            '不能确认时标uncertain；发现错误或歧义标invalid。不要根据外部知识补全资料。'
            '只返回JSON对象，字段verdict取valid、invalid或uncertain；reason为简洁中文说明。')
    def task(q):
        folder=REVIEW/'items'/q['id']; result=folder/'review.json'
        if result.exists(): return experiment.read(result)['verdict']
        if (folder/'requests').exists(): return 'unknown_hold'
        item=packet(q,gold[q['id']]); folder.mkdir(parents=True,exist_ok=True)
        body=dict(model='qwen3-8b',messages=[dict(role='system',content=prompt),
                  dict(role='user',content=json.dumps(item,ensure_ascii=False))],temperature=0,
                  max_tokens=512,enable_thinking=False,response_format={'type':'json_object'},stream=False)
        response=experiment.supercomputer_client(folder)(body,0)
        if response.get('status')!='response':
            experiment.save(result,dict(verdict='request_failed',status=response.get('status')))
            return 'request_failed'
        try:
            parsed=json.loads(response['response']['choices'][0]['message']['content'])
            if parsed.get('verdict') not in ('valid','invalid','uncertain') or not isinstance(parsed.get('reason'),str):
                raise ValueError('invalid review schema')
        except (ValueError,KeyError,TypeError,IndexError):
            parsed=dict(verdict='invalid_response',reason='审校响应不符合约定格式')
        experiment.save(result,parsed)
        return parsed['verdict']
    with ThreadPoolExecutor(max_workers=min(8,binding['deployment']['max_concurrency'])) as pool:
        selected=qs[:limit] if limit is not None else qs
        futures={pool.submit(task,q):q['id'] for q in selected}
        counts={}
        for future in as_completed(futures):
            status=future.result();counts[status]=counts.get(status,0)+1
            if sum(counts.values())%20==0: print('reviewed',sum(counts.values()),'/',len(qs),counts,flush=True)
    experiment.save(REVIEW/'summary.json',dict(counts=counts,total=len(qs),selected=len(selected),review_type='AI; not independent human review'))
    print(json.dumps(counts),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--check',action='store_true');parser.add_argument('--limit',type=int)
    args=parser.parse_args()
    if args.check:check()
    else:
        if args.limit is not None and args.limit<1:raise ValueError('limit must be positive')
        from central_execution import exclusive_lock
        REVIEW.mkdir(parents=True,exist_ok=True)
        with exclusive_lock(REVIEW/'review.lock'):run(args.limit)
