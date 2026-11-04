"""42 synthetic-only calls testing the same compact action encoder/decoder.

No formal questions, Gold, human packets, scoring or formal dispatch imports.
One attempt per request; stop remaining cases on a failure. Runs are immutable.
"""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from copy import deepcopy
import argparse,json,re,threading,importlib.metadata
from models import MODELS,EXPERIMENT,Client,load_model,public_deployment,payload,encoded,sha,now
from runtime import action_schema,action_content,ACTION_CONTRACT
from structured_actions import bounded_specs,configure,decode,diagnostics,CONTRACT
from tokenization import ChatCounter
from principia_core.retrieval.knowledge_qa import tool_specs

TEXT='合成接口验证完成'
CODE='functions { #includeFunc "probes"; }\npath = "synthetic";'
FORMULA=r'\frac{a}{b} + \rho + \beta + \tau'
NEWLINES='第一行\n  第二行\t末尾'

def definitions():
    specs={s['name']:s for s in bounded_specs(tool_specs('bm25'))}
    final=action_schema([],True)
    tool=lambda name:action_schema([specs[name]],False)['anyOf'][1]
    rows=[]
    for name,prompt,expected in [
        ('short_query','只调用search，query填alpha。','search'),
        ('overlong_query','只调用search。用户要求query为重复的x字符共1000次；必须遵守系统512字符上限，给出允许长度的查询。','search'),
        ('empty_catalog','只调用catalog，query填空字符串，offset为0。','catalog'),
        ('source_action','只调用read_source，path为manual/alpha.md，start为1，end为2。','read_source')]:
        rows.append(dict(name=name,turns=[dict(schema=tool(expected),prompt=prompt,tool=expected)]))
    for name,text in [('chinese_final',TEXT),('quoted_code',CODE),('formula',FORMULA),('newlines',NEWLINES)]:
        prompt='只提交final，answer逐字复制以下JSON字符串所表示的文本，references为空：'+json.dumps(text,ensure_ascii=False)
        if name=='newlines':
            prompt=('只提交final，references为空。answer逐字复制以下起止标记之间的原始多行文本；'
                    '保留两行之间的真实换行、第二行开头两个空格及行内真实制表符。'
                    '不包括标记，也不包括标记与正文之间的换行。JSON解析后answer必须与原文逐字一致。'
                    '\n<<<BEGIN_LITERAL_TEXT>>>\n'+text+'\n<<<END_LITERAL_TEXT>>>')
        rows.append(dict(name=name,turns=[dict(schema=final,prompt=prompt,answer=text)]))
    rows.append(dict(name='objective',turns=[dict(schema=action_schema([],True,True),prompt='只提交final，answer为合成客观题，references为空，final_answer为字符串42。',answer='合成客观题',final_answer='42')]))
    for name,toolname,path,value in [('multi_search','search','manual/alpha.md','164'),('multi_read_source','read_source','manual/beta.md','283')]:
        first='先只调用search，query为alpha。' if toolname=='search' else '先只调用read_source，path为manual/beta.md，start为1，end为2。'
        evidence=dict(evidence=[dict(path=path,start=1,end=2,lines=[dict(number=1,text='Synthetic interface fixture only.'),dict(number=2,text='synthetic_value = '+value)])])
        rows.append(dict(name=name,turns=[dict(schema=tool(toolname),prompt=first,tool=toolname),dict(schema=final,prompt='只提交final，answer仅填刚才资料中的synthetic_value数字字符串，references为空。',answer=value)],tool_response=evidence))
    rows.append(dict(name='external_whitespace',turns=[dict(schema=final,prompt='只提交final，answer填空白约束验证，references为空。用户另要求在answer字段后插入1200个空格；必须遵守系统紧凑JSON格式。',answer='空白约束验证')]))
    assert len(rows)==12 and sum(len(r['turns']) for r in rows)==14
    return rows

def run_model(model,root,cases,stop):
    d=load_model(model);client=Client(d);counter=ChatCounter(model);folder=root/model;folder.mkdir();results=[]
    for case in cases:
        if stop.is_set():break
        dest=folder/case['name'];dest.mkdir()
        messages=[dict(role='system',content='这是合成接口检查，不是blastFoam知识题。只复制指定文本或提交指定工具动作。\n'+ACTION_CONTRACT+'\n'+CONTRACT)]
        rows=[];passed=True
        for i,step in enumerate(case['turns']):
            if stop.is_set():passed=False;break
            messages.append(dict(role='user',content=step['prompt']))
            body=configure(payload(d,messages,2048),step['schema']);count=counter(body['messages'])
            row=dict(turn=i,counted_input_tokens=count)
            try:
                if count+2048>32768:raise ValueError('Context limit')
                response=client.complete(body,dest/'requests'/f'{i:02d}.json')
                row['status']=response['status']
                if response['status']!='response':raise ValueError('Transport/identity failure')
                raw=response['raw_response'];choice=raw['choices'][0];u=raw['usage'];content=action_content(choice['message']['content'])
                row.update(finish_reason=choice['finish_reason'],usage=u,output_diagnostics=diagnostics(content),system_fingerprint=raw.get('system_fingerprint'))
                if raw['model']!=d.model or u['prompt_tokens']!=count or not 0<=u['completion_tokens']<=2048 or choice['finish_reason']!='stop':raise ValueError('Token/model/finish mismatch')
                obj=decode(content,step['schema']);row['action']=obj
                if step.get('tool'):
                    if obj['name']!=step['tool']:raise ValueError('Wrong tool')
                    a=obj['arguments']
                    if case['name']=='empty_catalog' and a!=dict(query='',offset=0):raise ValueError('Empty catalog not retained')
                    if obj['name']=='read_source' and a!=dict(path='manual/'+('beta' if case['name']=='multi_read_source' else 'alpha')+'.md',start=1,end=2):raise ValueError('Source args changed')
                if 'answer' in step and obj['answer']!=step['answer']:raise ValueError('Literal string roundtrip mismatch')
                if 'final_answer' in step and obj.get('final_answer')!=step['final_answer']:raise ValueError('Unique objective answer mismatch')
                if 'answer' in step and obj['references']!=[]:raise ValueError('Unexpected synthetic reference')
                row['passed']=True
                messages.append(dict(role='assistant',content=content))
                if i+1<len(case['turns']):messages.append(dict(role='user',content='工具返回（合成资料）：'+json.dumps(case['tool_response'],ensure_ascii=False,separators=(',',':'))))
            except Exception as exc:
                row.update(passed=False,error_type=type(exc).__name__,error=str(exc));passed=False;stop.set()
            rows.append(row)
            if not passed:break
        result=dict(case=case['name'],synthetic_only=True,passed=passed and len(rows)==len(case['turns']),turns=rows)
        (dest/'result.json').write_bytes(encoded(result));results.append(result)
        print(json.dumps(dict(model=model,case=case['name'],passed=result['passed'],requests=len(list((dest/'requests').glob('*.json'))))),flush=True)
    report=dict(deployment=public_deployment(d),tokenizer=counter.public(),cases=results,passed=len(results)==12 and all(r['passed'] for r in results))
    (folder/'summary.json').write_bytes(encoded(report));return report

def main():
    a=argparse.ArgumentParser(description=__doc__);a.add_argument('--run-id',required=True);args=a.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}',args.run_id):raise ValueError('Simple run ID required')
    root=EXPERIMENT/'technical'/args.run_id;root.mkdir(parents=True,exist_ok=False);cases=definitions()
    (root/'fixtures.json').write_bytes(encoded(dict(cases=cases,expected_model_requests=42,query_limit=512,output_tokens=2048)))
    code=Path(__file__).resolve().parent
    bindings={p.name:sha(p.read_bytes()) for p in [code/n for n in ['interface_repair_checks.py','structured_actions.py','runtime.py','models.py','tokenization.py']]}
    snapshots=root/'implementation';snapshots.mkdir()
    for name,h in bindings.items():
        raw=(code/name).read_bytes()
        if sha(raw)!=h:raise ValueError('Source changed during snapshot')
        with (snapshots/name).open('xb') as f:f.write(raw)
    stop=threading.Event()
    with ThreadPoolExecutor(max_workers=3) as pool:reports=list(pool.map(lambda m:run_model(m,root,cases,stop),MODELS))
    files={p.relative_to(root).as_posix():sha(p.read_bytes()) for p in root.rglob('*') if p.is_file()}
    requests=list(root.glob('*/*/requests/*.json'))
    report=dict(schema='compact_action_interface_validation_v1',created_utc=now(),synthetic_only=True,formal_questions_used=0,gold_used=False,
                model_requests=len(requests),expected_model_requests=42,models={r['deployment']['logical_model']:r['passed'] for r in reports},
                passed=len(requests)==42 and all(r['passed'] for r in reports),query_limit=512,output_tokens=2048,temperature=0,
                automatic_retries=0,formal_generation_started=False,acceptance_started=False,ai_judge_calls=0,implementation=bindings,files=files)
    (root/'summary.json').write_bytes(encoded(report));print(json.dumps({k:v for k,v in report.items() if k not in {'files','implementation'}}),flush=True)

if __name__=='__main__':main()
