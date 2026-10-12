"""Read-only bridge to the reviewed dictionary and conditional dependency graph."""
from functools import lru_cache
import importlib
import hashlib
import json
from pathlib import Path
import sys


SKILL = Path(__file__).resolve().parents[2]/'.dsh/skills/blastfoam-knowledge'


@lru_cache(maxsize=1)
def navigator():
    scripts=SKILL/'scripts'
    sys.path.insert(0,str(scripts))
    try:
        bundle=importlib.import_module('evidence_bundle')
        condition=importlib.import_module('condition_graph')
        state=importlib.import_module('case_state')
        for module in (bundle,condition,state):
            if Path(module.__file__).resolve().parent!=scripts.resolve():
                raise RuntimeError('conflicting knowledge module loaded')
        index=json.loads((SKILL/'references/conditional_requirements.json').read_text())
        return condition.ConditionalEditSearch(bundle.EvidenceSearch(skill=SKILL),index)
    finally:
        sys.path.remove(str(scripts))


def locate(query,tutorial_case,translation='',budget=5000):
    return navigator().locate(query,tutorial_case,translation=translation,budget=budget)


def assess(case_path,tutorial_case,budget=5000):
    if not Path(case_path).is_dir():raise ValueError('case directory does not exist')
    return navigator().assess_case(case_path,tutorial_case,budget=budget)


def source(path,start=1,end=80,budget=5000):
    if type(start)!=int or type(end)!=int or start<1 or not start<=end or end-start>=1000:
        raise ValueError('invalid source range')
    if type(budget)!=int or not 1000<=budget<=24000:raise ValueError('invalid budget')
    engine=navigator().engine;engine.validate()
    if path not in engine.graph['inventory']:raise ValueError('source outside indexed corpus')
    root=(engine.skill/'corpus').resolve();file=(root/path).resolve()
    if not file.is_relative_to(root):raise ValueError('source escapes corpus')
    raw_bytes=file.read_bytes()
    if hashlib.sha256(raw_bytes).hexdigest()!=engine.graph['inventory'][path]:raise ValueError('source changed')
    lines=raw_bytes.decode().splitlines(keepends=True)
    if start>len(lines):raise ValueError('start exceeds source length')
    end=min(end,len(lines));raw=''.join(lines[start-1:end])
    result={'path':path,'start':start,'end':end,'sha256':engine.graph['inventory'][path],
            'text':raw,'complete':True}
    wire=lambda x:json.dumps(x,ensure_ascii=False,separators=(',',':'))
    if len(wire(result))>budget:
        result['complete']=False;result['text']=''
        lo=0;hi=len(raw)
        while lo<hi:
            mid=(lo+hi+1)//2;result['text']=raw[:mid]
            if len(wire(result))<=budget:lo=mid
            else:hi=mid-1
        result['text']=raw[:lo]
    if len(wire(result))>budget:return {'status':'insufficient_budget'}
    return result
