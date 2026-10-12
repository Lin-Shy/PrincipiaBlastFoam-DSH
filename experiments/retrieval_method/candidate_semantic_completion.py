"""对未完成来源细分补抽取；继承成功来源及其散列，不按题目选来源。"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
import fcntl
import json
from pathlib import Path
import re
import shutil
import time

import candidate_semantics as sem
import navigation_qa as qa
import graphify_qa as transport


def prepare(parent,output,output_tokens=8000,chunk_characters=1200):
    if output.exists():raise FileExistsError('preserve semantic completion stage')
    if not 300<=chunk_characters<=1200:raise ValueError('completion chunk characters must be 300..1200')
    protocol=sem.verify(parent);chunks=qa.read(parent/'chunks.json')
    output.mkdir(parents=True)
    inherited=qa.read(parent/'inherited.json') if (parent/'inherited.json').exists() else {}
    for item in inherited.values():
        if sem.digest(Path(item['path']).read_bytes())!=item['sha256']:raise ValueError('inherited extraction changed')
    todo={}
    for cid,chunk in chunks.items():
        valid=parent/'sessions'/cid/'validated.json'
        if valid.exists():
            inherited[cid]={'path':str(valid),'sha256':sem.digest(valid.read_bytes()),'chunk':chunk};continue
        path=chunk['path'];raw=(Path(protocol['corpus_root'])/path).read_bytes()
        if sem.digest(raw)!=chunk['source_sha256']:raise ValueError('source drift')
        lines=raw.decode().splitlines();first=chunk['primary_start'];end=chunk['end']
        while first<=end:
            last=first-1;size=0
            while last<end:
                amount=len(lines[last])+len(str(last+1))+3
                if size+amount>chunk_characters and last>=first:break
                size+=amount;last+=1
            stack=[]
            for n,line in enumerate(lines[:first-1],1):
                m=re.match(r'^(#{1,6})\s+',line)
                if m:
                    level=len(m[1]);stack=[v for v in stack if v['level']<level]
                    stack.append({'level':level,'line':n,'text':line})
            start=max(1,first-4)
            child={'path':path,'start':start,'primary_start':first,'end':last,'heading_context':stack,
                   'text':'\n'.join(f'{n}: {lines[n-1]}' for n in range(start,last+1)),
                   'source_sha256':chunk['source_sha256'],'parent_chunk':cid}
            identity=sem.digest([protocol['corpus_id'],'completion',path,first,last])[:24];child['id']=identity
            todo[identity]=child;first=last+1
    for name in ['candidate_semantic_completion.py','candidate_semantics.py','graphify_cross_source.py','graphify_structure.py',
                 'navigation_structure_parser.py','graphify_qa.py','navigation_qa.py','graphify_query_backend.py']:
        shutil.copy2(Path(__file__).with_name(name),output/name)
    qa.write(output/'chunks.json',todo);qa.write(output/'inherited.json',inherited)
    copied={k:v for k,v in protocol.items() if k!='files'}
    copied.update(schema='candidate-source-completion-v1',parent_root=str(parent),
                  parent_protocol_sha256=sem.digest((parent/'protocol.json').read_bytes()),
                  selection='every unvalidated parent primary source interval, no question/gold input',
                  chunk_character_target=chunk_characters,overlap_lines=4,output_tokens=output_tokens,
                  extract_prompt=protocol['extract_prompt']+'\n为避免反复复制长表格，evidence.quote只取该范围内足以定位的逐字短片段，最多80个字符；全局start/end仍覆盖完整支持文字和条件。不要把整章或整表重复放进每条quote。\n')
    copied['files']={p.name:sem.digest(p.read_bytes()) for p in output.iterdir() if p.is_file()}
    qa.write(output/'protocol.json',copied)
    print(qa.wire({'inherited':len(inherited),'new_source_chunks':len(todo)}))


def compile_layer(output,protocol):
    inherited=qa.read(output/'inherited.json');chunks=qa.read(output/'chunks.json')
    records=[];missing=[];coverage={};ranges={}
    def register(cid,chunk,path):
        c=coverage.setdefault(chunk['path'],{'planned':0,'validated':0});c['planned']+=1
        ranges.setdefault(chunk['path'],[]).append((chunk['primary_start'],chunk['end']))
        if path.exists():records.append(qa.read(path));c['validated']+=1
        else:missing.append(cid)
    for cid,item in inherited.items():
        p=Path(item['path'])
        if sem.digest(p.read_bytes())!=item['sha256']:raise ValueError('inherited source extraction changed')
        register(cid,item['chunk'],p)
    for cid,chunk in chunks.items():register(cid,chunk,output/'sessions'/cid/'validated.json')
    for path,intervals in ranges.items():
        expected=len((Path(protocol['corpus_root'])/path).read_bytes().decode().splitlines())
        numbers=[n for a,b in sorted(intervals) for n in range(a,b+1)]
        if numbers!=list(range(1,expected+1)):raise ValueError('source primary coverage has overlap or gap: '+path)
    layer={'schema':'candidate-full-source-semantics-v1','protocol_sha256':sem.digest((output/'protocol.json').read_bytes()),
           'corpus_id':protocol['corpus_id'],'records':records,'coverage':coverage,'missing_chunks':missing,
           'complete':not missing,'definitions':sum(len(r['definitions']) for r in records),
           'assertions':sum(len(r['assertions']) for r in records),'rejected':sum(len(r['rejected']) for r in records),
           'provenance':'validated inherited parent chunks plus finer unresolved source intervals; failed/aborted parent costs stay separate and must be included in construction total',
           'coverage_meaning':'all applicable prose lines processed and all extracted items verified; not proof every possible domain fact was extracted'}
    qa.write(output/'layer.json',layer);return layer


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument('command',choices=['prepare','run','compile'])
    cli.add_argument('--parent',type=Path);cli.add_argument('--output',type=Path,required=True)
    cli.add_argument('--key-file',type=Path);cli.add_argument('--workers',type=int,default=3)
    cli.add_argument('--output-tokens',type=int,default=8000)
    cli.add_argument('--chunk-characters',type=int,default=1200)
    a=cli.parse_args();output=a.output.resolve()
    if a.command=='prepare':prepare(a.parent.resolve(),output,a.output_tokens,a.chunk_characters);return
    protocol=sem.verify(output)
    if a.command=='compile':
        layer=compile_layer(output,protocol);print(qa.wire({k:layer[k] for k in ['complete','definitions','assertions','rejected']}));return
    if Path(__file__).resolve()!=output/'candidate_semantic_completion.py':raise ValueError('execute frozen completion runner')
    transport.SECRET=a.key_file.read_text().strip() if a.key_file else ''
    with (output/'runtime.lock').open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        with ThreadPoolExecutor(max_workers=a.workers) as pool:
            jobs={pool.submit(sem.process,output,c,protocol):cid for cid,c in qa.read(output/'chunks.json').items()}
            for f in as_completed(jobs):
                cid=jobs[f]
                try:r=f.result();print('COMPLETE_SOURCE',cid,len(r['definitions']),len(r['assertions']),flush=True)
                except Exception as e:
                    qa.write(output/'sessions'/cid/'failure.json',{'type':type(e).__name__,'reason':str(e)[:200]})
                    print('ERROR',cid,type(e).__name__,flush=True)
        compile_layer(output,protocol)


if __name__=='__main__':main()
