"""Manifest-backed Chapter 2 paths and explicit historical path/source bindings."""
from pathlib import Path
from functools import lru_cache
import hashlib,json

WORKSPACE=Path(str(Path(__file__).resolve().parents[3]).removeprefix('\\\\?\\'))
ROOT=WORKSPACE/'graduation-experiment-results/chapter2_retrieval'
DATA=ROOT/'data'
RESOURCES=DATA/'resources'

@lru_cache(maxsize=1)
def configuration():
    return json.loads((ROOT/'release/manifests/layout.json').read_text(encoding='utf-8'))

def asset(name):return ROOT/configuration()['assets'][name]

def resolve(path):
    p=Path(str(path).replace('\\','/'))
    text=str(p.absolute()).replace('\\','/').removeprefix('//?/')
    # Raw evidence stays byte-identical; its historical references resolve here.
    for row in configuration()['path_prefixes']:
        old=str(WORKSPACE/row['old']).replace('\\','/')
        if text.casefold()==old.casefold() or text.casefold().startswith(old.casefold().rstrip('/')+'/'):
            return WORKSPACE/row['new']/text[len(old):].lstrip('/')
    return p

def digest(path):
    h=hashlib.sha256()
    with resolve(path).open('rb') as f:
        for block in iter(lambda:f.read(4*1024*1024),b''):h.update(block)
    return h.hexdigest()

def source_equivalent(filename,expected,actual):
    if expected==actual:return True
    p=ROOT/'release/manifests/code_rebinding.json'
    if not p.exists():return False
    for row in json.loads(p.read_text(encoding='utf-8'))['files']:
        if Path(row['path']).name==filename and row['old_sha256']==expected and row['new_sha256']==actual:
            original=ROOT/row['original_file']
            return digest(original)==expected and digest(WORKSPACE/row['path'])==actual
    return False

def frozen_sources_match(expected,actual):
    return set(expected)==set(actual) and all(source_equivalent(k,expected[k],actual[k]) for k in expected)

def path_records_equal(a,b):
    """Compare frozen records with only explicit file-reference fields relocated."""
    def normalize(x):
        if isinstance(x,list):return [normalize(v) for v in x]
        if isinstance(x,dict):
            return {k:str(resolve(ROOT/v)).replace('\\','/').casefold() if k in ('parsed_file','source_file','source_path') and isinstance(v,str) else normalize(v) for k,v in x.items()}
        return x
    return normalize(a)==normalize(b)

def judge_request_matches(saved,profile,current):
    """Validate historical metadata while requiring identical judge wire inputs."""
    if saved['request']==current:return True
    historical=saved.get('profile')
    if not historical:return False
    from judge_api_adapter import digest
    old=dict(historical);new=dict(profile)
    old_registry=old.pop('registry_sha256',{});new_registry=new.pop('registry_sha256',{})
    if old!=new or set(old_registry)!=set(new_registry):return False
    receipt=json.loads((ROOT/'release/manifests/registry_rebinding.json').read_text(encoding='utf-8'))
    for name,before in old_registry.items():
        after=new_registry[name]
        if before==after:continue
        matches=[r for r in receipt['files'] if r['name']==name and r['old_sha256']==before and r['new_sha256']==after]
        if len(matches)!=1 or digest_file(ROOT/matches[0]['original_file'])!=before:return False
        if digest_file(WORKSPACE/'PrincipiaBlastFoam-DSH/config/llm'/name)!=after:return False
    if saved['request'].get('profile_sha256')!=digest(historical) or current.get('profile_sha256')!=digest(profile):return False
    return {k:v for k,v in saved['request'].items() if k!='profile_sha256'}=={k:v for k,v in current.items() if k!='profile_sha256'}

def digest_file(path):return digest(path)

def validate_manifest():
    p=asset('test_manifest');m=json.loads(p.read_text(encoding='utf-8'))
    for rel,expected in m['bindings'].items():
        if digest(WORKSPACE/rel)!=expected:raise ValueError('Frozen binding drift: '+rel)
    return m
