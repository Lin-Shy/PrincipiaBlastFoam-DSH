"""Seal model outputs and operator accounting; does not execute returned code."""
import hashlib
import json
import sys
import zipfile
from b11_live import pair,sha,write

arm=sys.argv[1]
assert arm in ('general','professional')
root=pair/arm
end=json.loads((root/'attempt_exit.json').read_bytes())
ledger=json.loads((root/'provider_ledger/ledger.json').read_bytes())
events=ledger['events']
safe=all(e['state']=='settled' for e in events)
output=root/'workspace/delivery'
items={}
with zipfile.ZipFile(pair/(arm+'.delivery.zip'),'x',compression=zipfile.ZIP_DEFLATED) as bundle:
    for f in sorted(output.rglob('*')):
        if f.is_symlink() or getattr(f.lstat(),'st_file_attributes',0)&1024:raise ValueError('unexpected output link')
        if f.is_file():
            rel=f.relative_to(output).as_posix()
            data=f.read_bytes()
            bundle.writestr(rel,data)
            items[rel]=hashlib.sha256(data).hexdigest()
receipt={'arm':arm,'exit':end,'requests':len(events),'all_settled':safe,'reported_tokens':{
    key:sum((e.get('usage') or {}).get(key,0) for e in events) for key in ('prompt_tokens','completion_tokens','total_tokens')},
    'unknown_requests':[e['request'] for e in events if e['state']!='settled'],'money':None,'cluster_jobs':0,
    'shared_host_account':True,'blind':False,'files':items,'archive_sha256':sha(pair/(arm+'.delivery.zip'))}
write(pair/(arm+'.receipt.json'),receipt)
print(json.dumps({k:v for k,v in receipt.items() if k not in ['files','exit']}),'files',list(items))
