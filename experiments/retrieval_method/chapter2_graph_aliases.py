"""Source-only bilingual graph aliases, proposed and checked by deepseek-flash."""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
from pathlib import Path
import time
from urllib.request import Request, ProxyHandler, build_opener
from urllib.error import HTTPError

from chapter2_offline_dataset_calls import key_from_config

MODEL = 'deepseek-flash'
ENDPOINT = 'https://api.deepseek.com/chat/completions'
PROPOSE = '''为专业技术资料构建中英双语检索别名。输入只有原文来源单元，没有问答题或评分标注。
对每个有意义的单元提出至多6个精炼中文别名，覆盖主题、模型、案例身份或关键参数含义。
别名必须仅由该单元原文支持，不加入常识推断、建议或未载明条件。保留技术标识的原拼写。
每条必须给出原文逐字quote。不要把完整问题写成别名。空白、目录或文件头返回空列表。
只输出JSON：{"aliases":[{"unit_id":"输入ID","aliases":["短中文词组"],"quote":"原文逐字片段"}]}。'''
VERIFY = '''核对原文来源单元和候选中文检索别名。输入不含题库或评分标准。
逐条核对：quote是否逐字存在，中文别名是否准确表达该单元明示内容，案例身份是否忠实。
不得接受仅由技术常识补足的条件、效果、模型等价或推荐。只输出JSON：
{"verdicts":[{"unit_id":"ID","accepted_aliases":["候选中通过的原字符串"],"reason":"简短理由"}]}。'''
def read(p): return json.loads(Path(p).read_text(encoding='utf-8-sig'))
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,v):
    p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('x',encoding='utf-8') as f: json.dump(v,f,ensure_ascii=False,indent=2)

def request(stage, payload, folder, key):
    p = folder/(stage+'.json')
    body = dict(model=MODEL, temperature=0, thinking={'type':'disabled'}, max_tokens=6000,
        response_format={'type':'json_object'}, messages=[dict(role='system',content=PROPOSE if stage=='propose' else VERIFY),
        dict(role='user',content=json.dumps(payload,ensure_ascii=False))])
    fingerprint = hashlib.sha256(json.dumps(body,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    if p.exists():
        old = read(p)
        if old['request_sha256'] != fingerprint: raise ValueError('Alias request identity changed')
        if old['status']=='in_flight': raise ValueError('Unresolved request cannot be replayed')
        return old
    record = dict(model=MODEL,endpoint=ENDPOINT,request=body,request_sha256=fingerprint,
        status='in_flight', transport_attempts=1, content_retries=0, started_unix=time.time())
    save(p,record); started=time.monotonic()
    try:
        req = Request(ENDPOINT,data=json.dumps(body,ensure_ascii=False).encode(),
            headers={'Content-Type':'application/json','Authorization':'Bearer '+key})
        with build_opener(ProxyHandler({})).open(req,timeout=120) as response:
            data=response.read(); record['http_status']=response.status
        raw=json.loads(data); record['raw_response']=raw
        if raw.get('model') != MODEL: raise ValueError('Returned model is not exact deepseek-flash')
        if raw['choices'][0].get('finish_reason') != 'stop': raise ValueError('Alias response unfinished')
        record['parsed']=json.loads(raw['choices'][0]['message']['content'])
        record['status']='response'
    except HTTPError as exc: record.update(status='http_rejected',http_status=exc.code)
    except (OSError,ValueError,KeyError,TypeError) as exc:
        record.update(status='failed',error_type=type(exc).__name__,reason=str(exc)[:160] if not isinstance(exc,OSError) else 'transport failure')
    finally:
        record['seconds']=time.monotonic()-started
        temp=p.with_suffix('.tmp');temp.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8');temp.replace(p)
    return record

def prepare(a):
    from chapter2_knowledge_input_guard import install
    guard=install()
    graph=read(a.graph)
    files={}
    for unit in graph['units'].values():
        if unit['kind']=='markdown_section': files.setdefault(unit['path'],[]).append(unit)
    tasks=[]
    # Every markdown source is included. Batches follow physical source order,
    # with no question/annotation filtering and a bounded 18000-character payload.
    for path, units in sorted(files.items()):
        current=[];chars=0
        for u in sorted(units,key=lambda v:v['start']):
            if current and chars+len(u['text'])>18000:
                tasks.append(dict(path=path,units=current));current=[];chars=0
            current.append(dict(unit_id=u['id'],path=u['path'],start=u['start'],end=u['end'],
                headings=u.get('context',[]),text=u['text']));chars+=len(u['text'])
        if current:tasks.append(dict(path=path,units=current))
    if a.output.exists():raise FileExistsError('New immutable alias construction required')
    save(a.output/'tasks.json',tasks)
    save(a.output/'protocol.json',dict(schema='source_only_bilingual_aliases_v1',model=MODEL,
        graph_sha256=sha(a.graph),tasks_sha256=sha(a.output/'tasks.json'),sources=len(files),
        source_units=sum(len(t['units']) for t in tasks),tasks=len(tasks),
        proposer_prompt=PROPOSE,verifier_prompt=VERIFY,source_sha256=sha(Path(__file__)),
        gold_or_questions_used=False,max_transport_attempts=1,content_retries=0,input_guard=guard))
    print(json.dumps(dict(sources=len(files),tasks=len(tasks),units=sum(len(t['units']) for t in tasks))))

def process(index, task, output, key):
    folder=output/'sessions'/f'{index:03d}'
    proposal=request('propose',task,folder,key)
    if proposal['status']!='response':return dict(task=index,stage='propose',status=proposal['status'])
    units={u['unit_id']:u for u in task['units']}; candidates=[]
    for row in proposal['parsed'].get('aliases',[]):
        if (row.get('unit_id') not in units or not isinstance(row.get('quote'),str) or not row['quote'].strip()
            or row['quote'] not in units[row['unit_id']]['text']):continue
        aliases=row.get('aliases')
        if not isinstance(aliases,list) or not all(isinstance(v,str) and 1<=len(v)<=40 for v in aliases):continue
        candidates.append(row)
    checked=request('verify',dict(source=task,candidate=candidates),folder,key)
    if checked['status']!='response':return dict(task=index,stage='verify',status=checked['status'])
    allowed={r['unit_id']:r for r in candidates};accepted=[]
    for row in checked['parsed'].get('verdicts',[]):
        uid=row.get('unit_id')
        if uid not in allowed:continue
        aliases=row.get('accepted_aliases',[])
        if not isinstance(aliases,list):continue
        aliases=[v for v in aliases if v in allowed[uid]['aliases']]
        if aliases:accepted.append(dict(unit_id=uid,aliases=aliases,quote=allowed[uid]['quote']))
    p=folder/'accepted.json'
    result=dict(task=index,path=task['path'],accepted=accepted,proposer_sha256=sha(folder/'propose.json'),
        verifier_sha256=sha(folder/'verify.json'),semantic_truth='AI source-grounding review, not human truth')
    if not p.exists():save(p,result)
    return dict(task=index,status='accepted',alias_units=len(accepted))

def run(a):
    protocol=read(a.output/'protocol.json')
    if protocol['source_sha256']!=sha(Path(__file__)) or protocol['tasks_sha256']!=sha(a.output/'tasks.json'):
        raise ValueError('Alias builder or input drift')
    key=key_from_config(a.dsh_home)
    from chapter2_knowledge_input_guard import install
    install()
    tasks=read(a.output/'tasks.json');indices=list(range(len(tasks)))
    if a.limit:indices=indices[:a.limit]
    results=[]
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        jobs=[pool.submit(process,i,tasks[i],a.output,key) for i in indices]
        for future in as_completed(jobs):
            row=future.result();results.append(row);print(json.dumps(row),flush=True)
    save(a.output/('completion-'+str(len(indices))+'.json'),dict(results=results,
        all_selected_completed=all(r['status']=='accepted' for r in results),selected=len(indices),total=len(tasks)))

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('command',choices=['prepare','run'])
    p.add_argument('--graph',type=Path);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--dsh-home',type=Path,default=Path('D:/1/dsh-home/chapter3'))
    p.add_argument('--workers',type=int,default=3);p.add_argument('--limit',type=int)
    a=p.parse_args();(prepare if a.command=='prepare' else run)(a)
if __name__=='__main__':main()
