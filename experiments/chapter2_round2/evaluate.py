"""独立离线评价；此进程可读评分，绝不被检索/Agent导入。"""
import argparse
from collections import defaultdict
import csv
import json
import statistics

from common import *

def evaluate_delivery(row,annotation,evidence,corpus):
    encoded=row['response']
    if len(encoded)!=row['response_characters'] or len(encoded)>row['budget']:
        raise ValueError('serialized delivery budget mismatch')
    if __import__('hashlib').sha256(encoded.encode()).hexdigest()!=row['response_sha256']:
        raise ValueError('serialized delivery hash mismatch')
    packet=json.loads(encoded);ledger=set();occurrences=0;chars=0;ranked=[]
    for item in packet.get('evidence',[]):
        if item['sha256']!=corpus.hashes[item['path']]:raise ValueError('source envelope hash mismatch')
        lines=corpus.lines(item['path'])
        local=set()
        for line in item['lines']:
            if lines[line['number']-1]!=line['text']:raise ValueError('source line text mismatch')
            key=(item['path'],line['number']);ledger.add(key);local.add(key)
            occurrences+=1;chars+=len(line['text'])
        ranked.append(local)
    if ledger!={(r['path'],r['line']) for r in row['delivered_lines']}:raise ValueError('delivery ledger differs from actual payload')
    required=[];gold_lines=set()
    for eid in annotation['required_evidence_ids']:
        e=evidence[eid]
        if e['file_sha256']!=corpus.hashes[e['path']]:raise ValueError('registered evidence source drift')
        span={(e['path'],n) for n in range(e['line_start'],e['line_end']+1)}
        required.append(span);gold_lines|=span
    full=[int(s<=ledger) for s in required]
    overlap=[len(s&ledger)/len(s) for s in required]
    gold_chars=sum(len(corpus.lines(p)[n-1]) for p,n in gold_lines&ledger)
    result=dict(id=row['id'],method=row['method'],budget=row['budget'],
        type=annotation['labels']['evidence_integration']+'_'+str(annotation['labels']['condition_discrimination']),
        group=annotation['split_group'],evidence_recall=sum(full)/len(full),all_evidence=int(all(full)),
        partial_evidence_overlap=sum(overlap)/len(overlap),any_evidence_overlap=int(any(overlap)),
        registered_line_recall=len(gold_lines&ledger)/len(gold_lines),registered_evidence_count=len(full),
        complete_evidence_count=sum(full),response_characters=len(encoded),text_characters=chars,
        registered_support_text_fraction=gold_chars/max(1,chars),
        duplicate_line_rate=1-len(ledger)/max(1,occurrences),rank_seconds=row['ranking_seconds'],
        delivery_seconds=row['delivery_seconds'],truncated=int(row['truncated']),
        semantic_support_coverage='pending_human_or_approved_semantic_check')
    cumulative=set();first=None
    for rank,s in enumerate(ranked,1):
        cumulative|=s
        if first is None and any(g<=cumulative for g in required):first=rank
    result['mrr_registered_complete_evidence']=0 if first is None else 1/first
    for k in [1,3,5,10]:
        got=set().union(*ranked[:k]) if ranked else set()
        result[f'recall_at_{k}']=sum(g<=got for g in required)/len(required)
        if k in [5,10]:result[f'all_evidence_at_{k}']=int(all(g<=got for g in required))
    return result

def aggregate(rows):
    numeric=[k for k,v in rows[0].items() if isinstance(v,(float,int)) and k!='budget']
    result=dict(n=len(rows),**{k:statistics.mean(r[k] for r in rows) for k in numeric})
    result['pooled_evidence_recall']=sum(r['complete_evidence_count'] for r in rows)/sum(r['registered_evidence_count'] for r in rows)
    result['p50_rank_seconds']=statistics.median(r['rank_seconds'] for r in rows)
    return result

def main(run_id,output):
    from principia_core.retrieval.knowledge_qa import FrozenKnowledgeCorpus
    corpus=FrozenKnowledgeCorpus(RESOURCES/'corpus',RESOURCES/'corpus-manifest.json')
    from functools import lru_cache
    corpus.lines=lru_cache(maxsize=None)(corpus.lines)
    annotations={a['id']:a for a in read(DATASET/'scoring/annotations.json')}
    evidence=read(DATASET/'scoring/evidence.json')
    all_rows=[];inputs={};statuses={}
    for folder in sorted((ARCHIVE/'runs'/run_id).iterdir()):
        if not folder.is_dir():continue
        complete=folder/'completed.json'
        if not complete.exists():statuses[folder.name]='incomplete_not_scored';continue
        c=read(complete)
        if c['smoke'] or c['questions']!=200 or c['deliveries']!=600:raise ValueError('full 200 x 3 required')
        f=folder/'deliveries.jsonl'
        if sha(f)!=c['deliveries_sha256']:raise ValueError('delivery file drift')
        rows=[json.loads(s) for s in f.read_text(encoding='utf-8').splitlines()]
        expected={(q['id'],b) for q in public_questions() for b in [2000,4000,6000]}
        if len(rows)!=600 or {(r['id'],r['budget']) for r in rows}!=expected:raise ValueError('missing or repeated question/budget')
        for r in rows:all_rows.append(evaluate_delivery(r,annotations[r['id']],evidence,corpus))
        inputs[folder.name]=dict(completed_sha256=sha(complete),deliveries_sha256=sha(f),load_seconds=c['load_seconds'],wall_seconds=c['wall_seconds'])
        statuses[folder.name]='complete'
    if not all_rows:raise ValueError('no completed methods')
    by=defaultdict(list);by_type=defaultdict(list)
    for r in all_rows:by[(r['method'],r['budget'])].append(r);by_type[(r['method'],r['budget'],r['type'])].append(r)
    summary=[dict(method=m,budget=b,**aggregate(rs)) for (m,b),rs in sorted(by.items())]
    types=[dict(method=m,budget=b,type=t,**aggregate(rs)) for (m,b,t),rs in sorted(by_type.items())]
    assert all(r['n']==200 for r in summary) and all(r['n']==50 for r in types)
    out=ARCHIVE/'evaluation'/output
    save(out/'summary.json',dict(schema='round2_retrieval_only_v1',run_id=run_id,methods=statuses,overall=summary,by_type=types,
         inputs=inputs,scoring_hashes={n:sha(DATASET/'scoring'/n) for n in ['annotations.json','evidence.json']},
         evaluator_sha256=sha(Path(__file__)),metrics='complete registered ranges on union of actually delivered original lines; partial is mean per-evidence covered-line fraction',
         boundaries='Registered evidence is non-exhaustive. No semantic gold support/QA/EAS inference. Timings include concurrent local indexing and are descriptive only. R@k refers to delivered source envelopes, not native nodes.'))
    save(out/'sessions.json',all_rows)
    for name,rows in [('overall',summary),('by_type',types),('sessions',all_rows)]:
        path=out/(name+'.csv')
        with path.open('x',encoding='utf-8-sig',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    lines=['# 固定查询检索结果（实际完成的方法）','','所有方法每档200题，类型各50。无生成Agent；本表不能解释为EAS。',
           '','|方法|预算字符|登记证据完整召回（逐题均值）|全部证据取得|部分证据行覆盖|平均实返字符|重复行率|',
           '|---|---:|---:|---:|---:|---:|---:|']
    for r in summary:
        lines.append(f"|{r['method']}|{r['budget']}|{r['evidence_recall']:.4f}|{r['all_evidence']:.4f}|{r['partial_evidence_overlap']:.4f}|{r['response_characters']:.1f}|{r['duplicate_line_rate']:.4f}|")
    lines+=['','目录状态：`'+wire(statuses)+'`。','',
            '登记证据不是穷尽相关性池；同义来源能否支持必要点尚未人工核验，状态pending。',
            '排名只计算一次，三个预算独立交付。路径、哈希、行号、JSON包络计入额度，只发送完整原文行。',
            'B3独立原文层次与图来源单元不同；A2保持完整图交付槽位且无回填。延时受到并发CPU索引影响，不作速度优劣检验。']
    (out/'retrieval_report.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(wire(dict(methods=statuses,rows=len(all_rows),output=str(out))))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--run-id',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();main(a.run_id,a.output)
