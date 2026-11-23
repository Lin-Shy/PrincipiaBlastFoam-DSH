"""Resolve the composed native plugin tree against its installed bundle anchors."""
import json
import hashlib
from pathlib import Path
import subprocess
import yaml

class JS(str):pass
class Loader(yaml.SafeLoader):pass
class Dumper(yaml.SafeDumper):pass
Loader.add_constructor('tag:yaml.org,2002:js',lambda l,n:JS(l.construct_scalar(n)))
Dumper.add_representer(JS,lambda d,s:d.represent_scalar('tag:yaml.org,2002:js',str(s)))

def runtime_node(runtime):
    identity=runtime.parent/'node_identity.json'
    if not identity.exists():return 'node'
    node=runtime.parent/'bin/node.exe'
    expected=json.loads(identity.read_text(encoding='utf-8'))['sha256']
    if hashlib.sha256(node.read_bytes()).hexdigest()!=expected:raise ValueError('Node snapshot changed')
    return str(node)

def prepare(root,runtime):
    rows=yaml.load((root/'dump.yml').read_text(encoding='utf-8'),Loader=Loader)
    def walk(rows):
        for row in rows:
            yield row
            if isinstance(row.get('config'),list):yield from walk(row['config'])
    names=sorted({r['name'] for r in walk(rows) if r.get('name','').startswith('@')})
    script='''const {createRequire}=require('node:module');const fs=require('node:fs');const {pathToFileURL}=require('node:url');
const input=JSON.parse(fs.readFileSync(0,'utf8'));const req=input.anchors.map(createRequire);const result={};
for(const name of input.names){for(const r of req){try{result[name]=pathToFileURL(r.resolve(name)).href;break;}catch{}}
if(!result[name])throw Error('unresolved plugin '+name);}process.stdout.write(JSON.stringify(result));'''
    anchors=[str(runtime/p/'package.json') for p in ['packages/bundle/base','packages/bundle/headless','apps/cli']]
    result=subprocess.run([runtime_node(runtime),'-e',script],input=json.dumps({'anchors':anchors,'names':names}),capture_output=True,text=True,check=True,timeout=30)
    paths=json.loads(result.stdout)
    for row in walk(rows):
        if row.get('name') in paths:row['name']=paths[row['name']]
    with (root/'boot.yml').open('x',encoding='utf-8') as f:yaml.dump(rows,f,Dumper=Dumper,allow_unicode=True,sort_keys=False)
    return paths
