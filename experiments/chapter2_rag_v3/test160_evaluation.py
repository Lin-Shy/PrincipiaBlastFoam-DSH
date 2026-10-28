"""Test160 scoring/statistics entry; owner confirmation precedes Test result/Gold reads."""
import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path

import single_pass_dev40 as s
import test160_runner as runner
import dev40_finalize as recovery
from judge_contract import VERSION


def authorize(path,mode='agentic'):
    if path is None:raise PermissionError('Test160 matrix has not been confirmed by the owner')
    approval=s.load(path)
    if approval.get('owner_confirmed') is not True or approval.get('manifest_sha256')!=s.sha(runner.MANIFEST):
        raise PermissionError('Owner confirmation must bind the exact Test manifest')
    if mode=='single_pass' and 'single_pass_3' not in approval.get('approved_supplements',[]):
        raise PermissionError('Single-Pass supplement is not included in the confirmed matrix')
    return runner.load_frozen()


def packet(authorization,mode='agentic'):
    manifest,questions=authorize(authorization,mode)
    out=s.RUN/('test160_runs' if mode=='agentic' else 'test160_runs/supplement/single_pass')
    annotations={x['id']:x for x in s.load(s.WORKSPACE/manifest['scoring_only']['annotations'])}
    gold=s.load(s.WORKSPACE/manifest['scoring_only']['evidence'])
    items=[]
    configs=[c for c in manifest['configurations'] if mode=='agentic' or c['method_id'] in ('graph','bm25','bge_m3')]
    expected=len(configs)*160
    for c in configs:
        for q in questions:
            p=out/'generation'/c['config_id']/q['id']/'result.json'
            if not p.exists():raise ValueError('Complete generation/reconciliation before scoring: '+str(p))
            raw=s.load(p)
            if raw.get('manifest_sha256')!=s.sha(runner.MANIFEST):raise ValueError('Generation manifest mismatch')
            a=annotations[q['id']];sources=[];seen=set()
            for eid in a['required_evidence_ids']:
                e=gold[eid]
                if e['path'] in seen:continue
                seen.add(e['path']);fp=s.RUN/'data/resources/corpus'/e['path']
                if s.sha(fp)!=e['file_sha256']:raise ValueError('Gold source hash drift')
                text='\n'.join('%d|%s'%(i,line) for i,line in enumerate(fp.read_text(encoding='utf-8-sig').splitlines(),1))
                sources.append(dict(path=e['path'],file_sha256=e['file_sha256'],text=text))
            item=dict(schema_version=VERSION,sample_id='T'+hashlib.sha256((c['config_id']+'|'+q['id']+'|'+s.sha(p)).encode()).hexdigest()[:20],
                question=q['question'],answer=raw.get('answer') or '',generation_failed=raw['status']!='answered',
                criteria=[dict(criterion_id='K%03d'%(i+1),claim=z['claim']) for i,z in enumerate(a['required_points'])],
                conditional=a['labels']['condition_discrimination'],sources=sources)
            items.append(dict(model=c['logical_model'],method=c['method_id'],qid=q['id'],item=item,
                              generation_file=p.relative_to(s.RUN).as_posix(),generation_sha256=s.sha(p)))
    compact=set()
    for row in items:
        if row['item']['generation_failed']:continue
        try:recovery.request('gpt_sol',row['item'])
        except ValueError as exc:
            if 'exceeds' not in str(exc):raise
            compact.add(row['qid'])
    for row in items:
        if row['qid'] in compact:
            for source in row['item']['sources']:
                source['text']='\n'.join(z for z in source['text'].splitlines() if z.partition('|')[2].strip())
        if not row['item']['generation_failed']:
            for judge in s.JUDGES:recovery.request(judge,row['item'])
    proto=dict(schema='test160_dual_scoring',scope=dict(generation_sessions=expected),
               test_manifest_sha256=s.sha(runner.MANIFEST),test160=True,execution_mode=mode)
    destination=out/'protocol.json'
    if destination.exists() and s.load(destination)!=proto:raise ValueError('Scoring protocol drift')
    if not destination.exists():s.save(destination,proto)
    value=dict(count=expected,items=items,protocol_sha256=s.sha(destination),whitespace_compacted_question_ids=sorted(compact))
    p=out/'scoring/packet.json'
    if p.exists() and s.load(p)!=value:raise ValueError('Never alter a previously requested Test packet')
    if not p.exists():s.save(p,value)
    return value


def score(authorization,mode='agentic'):
    packet(authorization,mode)
    # Reuse the same bounded transport after the explicit Test authorization check.
    s.OUT=s.RUN/('test160_runs' if mode=='agentic' else 'test160_runs/supplement/single_pass');recovery.RETRY_INVALID=True
    from concurrent.futures import ThreadPoolExecutor
    from central_execution import exclusive_lock
    def lane(judge):
        with exclusive_lock(s.OUT/('finalize_'+judge+'.lock')):return recovery.score(judge,2,True)
    with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(lane,s.JUDGES))


def analyze(authorization,mode='agentic'):
    manifest,questions=authorize(authorization,mode)
    from dev40_final_analysis import judged,evidence,summarize
    out=s.RUN/('test160_runs' if mode=='agentic' else 'test160_runs/supplement/single_pass');p=s.load(out/'scoring/packet.json')
    annotations={x['id']:x for x in s.load(s.WORKSPACE/manifest['scoring_only']['annotations'])}
    gold=s.load(s.WORKSPACE/manifest['scoring_only']['evidence'])
    rows=[]
    for row in p['items']:
        file=s.RUN/row['generation_file']
        if s.sha(file)!=row['generation_sha256']:raise ValueError('Generation drift')
        r=s.load(file);failed=r['status']!='answered'
        rows.append(dict(model=row['model'],method=row['method'],question_id=row['qid'],conditional=row['item']['conditional'],generation_failed=failed,
            score=judged(out/'scoring',row['item'],failed),evidence=evidence(row['qid'],r.get('delivered_lines',[]),annotations,gold),
            characters=r.get('knowledge_characters',0),tool_calls=len(r.get('tool_events',[])),
            prompt_tokens=r.get('counted_input_tokens'),completion_tokens=r.get('actual_completion_tokens')))
    groups=[dict(model=c['logical_model'],method=c['method_id'],summary=summarize([r for r in rows if r['model']==c['logical_model'] and r['method']==c['method_id']])) for c in manifest['configurations'] if mode=='agentic' or c['method_id'] in ('graph','bm25','bge_m3')]
    s.save(out/'analysis/results.json',dict(groups=groups,per_answer=rows,manifest_sha256=s.sha(runner.MANIFEST)))
    import html
    (out/'analysis/index.html').write_text('<!doctype html><meta charset="utf-8"><title>Test160</title><h1>Test160固定分母结果</h1><pre>'+html.escape(json.dumps(groups,ensure_ascii=False,indent=2))+'</pre>',encoding='utf-8')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('command',choices=['prepare','score','analyze']);p.add_argument('--authorization',type=Path)
    p.add_argument('--mode',choices=['agentic','single_pass'],default='agentic');a=p.parse_args()
    {'prepare':packet,'score':score,'analyze':analyze}[a.command](a.authorization,a.mode)
