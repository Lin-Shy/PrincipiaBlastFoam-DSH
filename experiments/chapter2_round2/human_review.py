"""固定种子、盲法人评导出及真实人工标签汇总；不调用LLM。"""
import argparse
from collections import Counter,defaultdict
import csv
import hashlib
import random
import statistics

from common import *

SEED=20261020

def stratified(rows,key,n,rng):
    groups=defaultdict(list)
    for r in rows:groups[key(r)].append(r)
    if n<len(groups):raise ValueError('sample cannot represent all strata')
    for group in groups.values():rng.shuffle(group)
    allocation={k:1 for k in groups}
    while sum(allocation.values())<n:
        eligible=[k for k in groups if allocation[k]<len(groups[k])]
        k=min(eligible,key=lambda k:(-(len(groups[k])*n/len(rows)-allocation[k]),str(k)))
        allocation[k]+=1
    return [r for k in sorted(groups,key=str) for r in groups[k][:allocation[k]]],{str(k):allocation[k] for k in groups}

def export():
    from principia_core.retrieval.knowledge_qa import FrozenKnowledgeCorpus
    corpus=FrozenKnowledgeCorpus(RESOURCES/'corpus',RESOURCES/'corpus-manifest.json')
    out=ARCHIVE/'human_review';out.mkdir(parents=True,exist_ok=False)
    annotations=read(DATASET/'scoring/annotations.json');evidence=read(DATASET/'scoring/evidence.json')
    questions={q['id']:q['question'] for q in public_questions()}
    rng=random.Random(SEED)
    strata=defaultdict(list)
    for a in annotations:strata[(a['labels']['evidence_integration'],a['labels']['condition_discrimination'])].append(a)
    picked=[]
    for key in sorted(strata):picked+=rng.sample(sorted(strata[key],key=lambda a:a['id']),10)
    pairs=[(a,arm) for a in picked for arm in ['graph','bm25']];rng.shuffle(pairs)
    forms=[];keys=[];ratings=[]
    for i,(a,arm) in enumerate(pairs,1):
        sample_id=f'R{i:03d}'
        path=HISTORICAL/'generation'/arm/a['id']/'result.json';answer=read(path)
        ev=[]
        for eid in a['required_evidence_ids']:
            e=evidence[eid];source=corpus.read(e['path'],e['line_start'],e['line_end'])
            ev.append(dict(evidence_id=eid,source=source))
        forms.append(dict(sample_id=sample_id,question_id=a['id'],question=questions[a['id']],
            conditional=a['labels']['condition_discrimination'],required_points=a['required_points'],
            applicability=a['applicability'],critical_errors=a['critical_errors'],
            raw_answer=answer['answer'],references=answer['references'],generation_status=answer['status'],
            evidence=ev,review_status='pending',instructions='Independently judge raw answer; do not consult method key or AI judgments. Full1/partial0.5/omitted0/wrong0; facts and conditions pass/fail/unknown.'))
        keys.append(dict(sample_id=sample_id,question_id=a['id'],arm=arm,answer_file=path.relative_to(WORKSPACE).as_posix(),
                         answer_sha256=sha(path),score_file=(HISTORICAL/'scoring_001/sessions'/arm/a['id']/'result.json').relative_to(WORKSPACE).as_posix()))
        for reviewer in ['reviewer_1','reviewer_2']:
            ratings.append(dict(sample_id=sample_id,reviewer_id=reviewer,review_status='pending',
                points=[dict(point_id=p['id'],label='',reason='') for p in a['required_points']],
                factuality='',factuality_reason='',applicability='',applicability_reason=''))
    save(out/'blinded_answers.json',forms)
    save(out/'ratings_template.json',ratings)
    save(out/'evaluation_only/method_key.json',keys)
    graph=read(GRAPH)
    nodes,node_alloc=stratified(list(graph['nodes'].values()),lambda n:n['kind'],50,rng)
    edges,edge_alloc=stratified(graph['edges'],lambda e:(e['relation'],e['cross_owner']),50,rng)
    aliases=[dict(node_id=n['id'],alias=alias,path=n['path'],evidence=n['evidence'])
             for n in graph['nodes'].values() if n.get('alias_grounding')
             for g in n['alias_grounding'] for alias in g['aliases']]
    if len(aliases)!=1322:raise ValueError('unexpected generated aliases count')
    alias_sample=rng.sample(aliases,30)
    def sources(node):
        return [corpus.read(e['path'],e['start'],e['end']) for e in node['evidence']]
    node_forms=[dict(node=n,sources=sources(n),judgment='',error_type='',reviewer_id='',reason='',status='pending') for n in nodes]
    edge_forms=[dict(edge=e,source_node=graph['nodes'][e['source']],target_node=graph['nodes'][e['target']],
        source_evidence=sources(graph['nodes'][e['source']]),target_evidence=sources(graph['nodes'][e['target']]),
        judgment='',error_type='',reviewer_id='',reason='',status='pending') for e in edges]
    alias_forms=[dict(alias=a,sources=sources(graph['nodes'][a['node_id']]),judgment='',error_type='',
                      reviewer_id='',reason='',status='pending') for a in alias_sample]
    save(out/'graph_nodes_50.json',node_forms);save(out/'graph_edges_50.json',edge_forms);save(out/'graph_aliases_30.json',alias_forms)
    save(out/'sampling_manifest.json',dict(seed=SEED,questions=40,types_each=10,answers=80,
        reviewers_requested=2,reviewer_records=160,nodes=50,edges=50,aliases=30,
        node_strata=node_alloc,edge_strata=edge_alloc,alias_sampling='uniform without replacement among1322 generated alias entries',
        input_graph_sha256=sha(GRAPH),question_ids=[a['id'] for a in picked],
        labels_status='pending',human_agreement='pending',graph_accuracy='pending',
        leakage_notice='Human review export is scoring-side only. Never add it to corpus or production inputs.',
        files={p.relative_to(out).as_posix():sha(p) for p in out.rglob('*.json')}))
    (out/'README.md').write_text('# 人工核验材料\n\n40题四类各10，完整图/BM25原始回答共80份。评审只接收 blinded_answers.json 与各自 ratings_template.json 副本；不提供 evaluation_only 方法键或AI评分。两人独立填写，分歧交第三人裁决；未回填全部 pending。\n\n图谱按节点类型与(关系类型,是否跨owner)分层比例抽样，各层至少1，再按比例最大缺额补足；别名在1322条中等概率抽30。分层分母在 sampling_manifest.json。\n\n不可将题目人工审核或这份空表解释为回答评分、图正确率。`human_review.py aggregate --ratings <人工回填文件> --output <新报告目录>` 只聚合真实标签；未知保留上下界。\n',encoding='utf-8')
    print('exported 80 blinded answers,160 pending reviewer records,50/50/30 graph samples')

def kappa(left,right):
    labels=sorted(set(left+right));n=len(left)
    if not n:return None
    a=Counter(left);b=Counter(right);observed=sum(x==y for x,y in zip(left,right))/n
    expected=sum(a[k]*b[k] for k in labels)/(n*n)
    return dict(n=n,agreement=observed,kappa=None if expected==1 else (observed-expected)/(1-expected),
                left_distribution=dict(a),right_distribution=dict(b))

def weighted_kappa(left,right):
    values={'full':1,'partial':.5,'omitted':0,'wrong':0}
    pairs=[(values[x],values[y]) for x,y in zip(left,right) if x in values and y in values]
    if not pairs:return None
    n=len(pairs);a=Counter(x for x,y in pairs);b=Counter(y for x,y in pairs)
    observed=sum((x-y)**2 for x,y in pairs)/n
    expected=sum(ax*by*(x-y)**2 for x,ax in a.items() for y,by in b.items())/(n*n)
    return dict(n=n,excluded_unknown=len(left)-n,quadratic_weighted_kappa=None if expected==0 else 1-observed/expected,
                note='omitted and wrong share score0; unweighted category agreement reported separately')

def aggregate(path,output):
    ratings=read(path);forms={r['sample_id']:r for r in read(ARCHIVE/'human_review/blinded_answers.json')}
    seen=set();accepted=[];pending=0
    for r in ratings:
        key=(r['sample_id'],r['reviewer_id'])
        if key in seen:raise ValueError('duplicate reviewer/sample')
        seen.add(key)
        if r['review_status']!='complete':pending+=1;continue
        form=forms[r['sample_id']];points={p['point_id']:p['label'] for p in r['points']}
        weights={p['id']:p['weight'] for p in form['required_points']}
        if set(points)!=set(weights) or any(v not in ['full','partial','omitted','wrong','unknown'] for v in points.values()):raise ValueError('invalid point labels')
        if not r['reviewer_id'].strip() or r['factuality'] not in ['pass','fail','unknown']:raise ValueError('reviewer/factuality required')
        if form['conditional'] and r['applicability'] not in ['pass','fail','unknown']:raise ValueError('condition label required')
        total=sum(weights.values());lo=sum(weights[k]*{'full':1,'partial':.5}.get(v,0) for k,v in points.items())/total
        hi=lo+sum(weights[k] for k,v in points.items() if v=='unknown')/total
        fact=r['factuality'];cond=r['applicability'] if form['conditional'] else 'pass'
        lower=100*lo*(fact=='pass')*(cond=='pass');upper=100*hi*(fact!='fail')*(cond!='fail')
        if form['generation_status']!='answered':lower=upper=0
        accepted.append(dict(sample_id=r['sample_id'],reviewer_id=r['reviewer_id'],points=points,factuality=fact,applicability=cond,eas_lower=lower,eas_upper=upper))
    pairs=defaultdict(list)
    for r in accepted:pairs[r['sample_id']].append(r)
    if len({r['reviewer_id'] for r in accepted})>2:
        raise ValueError('more than two primary reviewers; adjudicator labels must be separate')
    point_left=[];point_right=[];fl=[];fr=[];al=[];ar=[]
    for pair in pairs.values():
        if len(pair)==2:
            x,y=sorted(pair,key=lambda r:r['reviewer_id'])
            for k in x['points']:point_left.append(x['points'][k]);point_right.append(y['points'][k])
            fl.append(x['factuality']);fr.append(y['factuality'])
            if forms[x['sample_id']]['conditional']:
                al.append(x['applicability']);ar.append(y['applicability'])
    comparisons=[]
    if accepted:
        key={r['sample_id']:r for r in read(ARCHIVE/'human_review/evaluation_only/method_key.json')}
        ai={(r['arm'],r['id']):r for r in read(HISTORICAL/'analysis_001/session-metrics.json')}
        for r in accepted:
            k=key[r['sample_id']];old=ai[(k['arm'],k['question_id'])]
            comparisons.append(dict(sample_id=r['sample_id'],reviewer_id=r['reviewer_id'],
                human_minus_ai_eas_lower=r['eas_lower']-100*old['score_upper'],
                human_minus_ai_eas_upper=r['eas_upper']-100*old['score_lower'],
                boundary='individual reviewer sensitivity, not adjudicated consensus; historical AI judgments unchanged'))
    save(ARCHIVE/'reports'/output/'human_summary.json',dict(status='pending' if not accepted else 'partial' if pending else 'filled',
        completed=len(accepted),pending=pending,point_agreement=kappa(point_left,point_right),
        point_quadratic_weighted_agreement=weighted_kappa(point_left,point_right),
        factuality_agreement=kappa(fl,fr),applicability_agreement=kappa(al,ar),ratings=accepted,
        ai_human_difference=comparisons or 'pending real human labels',
        input_sha256=sha(path),script_sha256=sha(Path(__file__))))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['export','aggregate']);p.add_argument('--ratings',type=Path);p.add_argument('--output')
    a=p.parse_args()
    export() if a.action=='export' else aggregate(a.ratings,a.output)
