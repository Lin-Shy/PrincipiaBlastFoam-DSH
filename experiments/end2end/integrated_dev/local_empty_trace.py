"""Summarize tool requests and residual work only for sealed empty deliveries."""
import json
from local_wave_report import summarize
from b11_live import base,batch

for row in summarize():
    if not row['receipt'] or row['delivery']:continue
    task,arm=row['id'],row['arm']
    receipt = (batch / row['receipt']).resolve()
    root = receipt.parent if receipt.name == 'sealed.json' else receipt.parent / arm
    sketch=[]
    for resp in sorted((root/'provider_ledger').glob('response-*.bin')):
        calls={}
        for line in resp.read_bytes().decode('utf-8').splitlines():
            if not line.startswith('data:') or line[5:].strip()=='[DONE]':continue
            for c in json.loads(line[5:]).get('choices',[]):
                for tool in c.get('delta',{}).get('tool_calls') or []:
                    item=calls.setdefault(tool['index'],['',''])
                    for i,k in enumerate(('name','arguments')):item[i]+=tool.get('function',{}).get(k) or ''
        for name,args in calls.values():
            sketch.append({'request':resp.stem,'tool':name,'args_excerpt':args[:320]})
    workspace=root/'workspace'
    paths=[p.relative_to(workspace).as_posix() for p in workspace.rglob('*') if p.is_file()]
    out=batch/'local_reviews'/task;out.mkdir(parents=True,exist_ok=True)
    path=out/(arm+'.empty_trace.json')
    if not path.exists():path.write_text(json.dumps(dict(files_outside_submission=paths,requested_calls=sketch),ensure_ascii=False,indent=2),encoding='utf-8')
