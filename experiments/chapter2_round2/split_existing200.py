"""Repartition existing, reviewed200 IDs and summarize immutable scored rows.

No new questions, annotation copies, answer generation, judging or tuning.
Researcher's correction of the tuning history is recorded as an attestation;
existing frozen execution records keep their bytes and original timestamps.
"""
import argparse
from collections import Counter
from datetime import datetime,timezone
import csv
from common import *

SPLIT=DATASET.parent/'split_dev160_test40_20261020.json'
OUT=ARCHIVE/'split160_40_20261020'

def kind(a):
    return ('S'if a['labels']['evidence_integration']=='single'else'M')+str(int(a['labels']['condition_discrimination']))

def freeze():
    metadata=read(DATASET/'dataset.json');questions=public_questions();anns={a['id']:a for a in read(DATASET/'scoring/annotations.json')};ev=read(DATASET/'scoring/evidence.json')
    ids=[q['id']for q in questions];test=set(metadata['new_ids']);dev=set(ids)-test
    if len(ids)!=len(set(ids))or len(ids)!=200 or len(test)!=40 or len(dev)!=160:raise ValueError('existing160/40 cohort drift')
    def details(selected):
        rows=[anns[i]for i in ids if i in selected];eids={eid for a in rows for eid in a['required_evidence_ids']}
        return dict(ids=[i for i in ids if i in selected],questions=len(selected),types=dict(Counter(kind(a)for a in rows)),themes=sorted({a['theme_id']for a in rows}),
            knowledge_groups=sorted({a['split_group']for a in rows}),required_points=sum(len(a['required_points'])for a in rows),evidence_units=len(eids),source_files=sorted({ev[e]['path']for e in eids}))
    d,t=details(dev),details(test)
    def lines(selected):return {(ev[e]['path'],n)for qid in selected for e in anns[qid]['required_evidence_ids']for n in range(ev[e]['line_start'],ev[e]['line_end']+1)}
    save(SPLIT,dict(schema='existing200_development160_test40_v1',recorded_utc=datetime.now(timezone.utc).isoformat(),source_dataset='formal_v2_200',
        source_sha256={name:sha(DATASET/name)for name in ['dataset.json','model/questions.json','scoring/annotations.json','scoring/evidence.json']},
        assignment_rule='Existing original160 IDs are development; existing new_ids40 are test. No random redraw, no method-score inputs.',
        development=d,test=t,overlap=dict(question_ids=sorted(dev&test),themes=sorted(set(d['themes'])&set(t['themes'])),knowledge_groups=sorted(set(d['knowledge_groups'])&set(t['knowledge_groups'])),
            registered_source_files=sorted(set(d['source_files'])&set(t['source_files'])),registered_source_line_count=len(lines(dev)&lines(test))),
        researcher_confirmation=dict(confirmed=True,basis='Researcher explicitly corrected unsynchronized prior records in this session; not an independent retrospective audit.',
            user_statements=['前者用来参数调参（目前我已经对各个方法进行调参过了，直接使用），另外40道题做独立测试。你直接沿用原有的实验结果内容和文件，我已经审核过了没有问题。',
                '现有记录是存在错误、没有同步，我说的可以就是可以，将其写成“从未参与调参的未见留出集”'],
            interpretation='Only original160 used for tuning; original40 were unseen to tuning and are the held-out test set. Existing all200 generation and scoring are reused; no claim that tests have never been executed.',
            recorded_now_not_backdated=True),
        policy=dict(new_question_data=False,new_generation=False,new_judging=False,new_tuning=False,original_answers_and_scores_unchanged=True,
            primary_reporting='test40',development_reporting='development160 descriptive results; existing tuned settings reused',failure='zero',unknown='retain identification bounds; no imputation or rescore',
            group_inference='Use actual groups within each split, not the full-bank24 count; cluster bootstrap and exact sign test; separate Holm families',
            scope='Unseen questions to tuning per researcher confirmation; not unseen documents, graphs or physical validation'),
        source_sha256_script=sha(Path(__file__))))
    print('Bound existing IDs only: development160/test40; no new dataset or API calls')

def verify():
    p=read(SPLIT)
    for name,h in p['source_sha256'].items():
        if sha(DATASET/name)!=h:raise ValueError('original200 input drift')
    d=p['development']['ids'];t=p['test']['ids']
    if len(d)!=160 or len(t)!=40 or set(d)&set(t)or set(d+t)!={q['id']for q in public_questions()}:raise ValueError('partition invalid')
    return p

def summarize_grid(rows,arms,ids,with_comparisons):
    from chapter2_model14b_analysis_200 import summarize,effect_intervals,holm
    from chapter2_metric_revision_200 import graded_validity,valid_at_threshold
    ids=set(ids);selected=[r for r in rows if r['arm']in arms and r['id']in ids]
    if len(selected)!=len(ids)*len(arms)or len({(r['arm'],r['id'])for r in selected})!=len(selected):raise ValueError('missing or duplicate split/method rows')
    for r in selected:
        if graded_validity(r)!=(r['score_lower'],r['score_upper'])or valid_at_threshold(r,1)!=(r['cv_lower'],r['cv_upper']):raise ValueError('frozen metric not reproduced')
        if r['generation_status']!='answered'and(r['score_lower']or r['score_upper']or r['cv_upper']):raise ValueError('failure excluded or scored')
    by={a:sorted([r for r in selected if r['arm']==a],key=lambda r:r['id'])for a in arms}
    def optional(rs):return summarize(rs)if rs else None
    groups=sorted({r['group']for r in selected});comparisons={}
    main=[a for a in arms if a not in ['graph','graph_no_cross','graph_no_aliases','no_traversal','anchor_only']]
    ablations=[a for a in arms if a in ['graph_no_cross','graph_no_aliases','no_traversal','anchor_only']]
    if with_comparisons:
        for family,others in [('primary',main),('ablation',ablations)]:
            effects=[]
            for arm in others:
                g=by['graph'];b=by[arm]
                if [r['id']for r in g]!=[r['id']for r in b]or [r['group']for r in g]!=[r['group']for r in b]:raise ValueError('split pairing changed')
                v=effect_intervals([[r['score_lower'],r['score_upper']]for r in g],[[r['score_lower'],r['score_upper']]for r in b],[r['group']for r in g])
                v.update(comparison='graph vs '+arm,practical_threshold=.05,practical_positive_identified=v['difference_lower']>=.05);effects.append(v)
            for v,padj in zip(effects,holm([v['exact_cluster_sign_randomization_p_upper']for v in effects])):v.update(holm_p_upper=padj,statistical_positive_identified=v['difference_lower']>0 and padj<.05)
            comparisons[family]=effects
    return dict(question_count=len(ids),sessions=len(selected),knowledge_groups=len(groups),group_ids=groups,
        by_arm={a:summarize(rs)for a,rs in by.items()},by_type={a:{k:optional([r for r in rs if r['type']==k])for k in ['S0','S1','M0','M1']}for a,rs in by.items()},
        by_group={a:{g:optional([r for r in rs if r['group']==g])for g in groups}for a,rs in by.items()},comparisons=comparisons,
        inference='Test split: actual knowledge-group paired bootstrap10000, seed20261019, exact sign randomization and separate Holm families'if with_comparisons else'Development split descriptive only; no retuning'),selected

def analyze(include_round2=False):
    p=verify()
    sources={model:CURRENT/'basic_search_200_20261019_001'/('qwen3-'+model)/'analysis_001'for model in ['8b','14b']}
    if include_round2:sources['round2_14b']=ARCHIVE/'e2e_runs/answer14b_003/analysis_001'
    for model,source in sources.items():
        destination=OUT/model
        if destination.exists():
            manifest=read(destination/'binding.json')
            if manifest['split_sha256']!=sha(SPLIT)or manifest['source_rows_sha256']!=sha(source/'session-metrics.json'):raise ValueError('closed reused split changed')
            print('Already closed split analysis, unchanged:',model);continue
        full=read(source/'summary.json');rows=read(source/'session-metrics.json');arms=list(full['by_arm'])
        if len(rows)!=200*len(arms)or full.get('question_count',200)!=200:raise ValueError('full-bank source incomplete')
        hashes={str(path.relative_to(WORKSPACE)):sha(path)for path in [source/'summary.json',source/'session-metrics.json']}
        for name in ['development','test']:
            summary,selected=summarize_grid(rows,arms,p[name]['ids'],name=='test')
            summary.update(schema='reused_existing200_split_v1',split=name,split_sha256=sha(SPLIT),answer_model='qwen3-14b'if model in ['14b','round2_14b']else'qwen3-8b',
                original_sources_sha256=hashes,new_generation_calls=0,new_judge_calls=0,score_policy='Reuse exact original rows; no human/AI score revision')
            save(destination/name/'summary.json',summary);save(destination/name/'session-metrics.json',selected)
            with(destination/name/'session-metrics.csv').open('x',encoding='utf-8-sig',newline='')as f:
                writer=csv.DictWriter(f,fieldnames=list(selected[0]));writer.writeheader();writer.writerows(selected)
        save(destination/'binding.json',dict(split_sha256=sha(SPLIT),source_rows_sha256=sha(source/'session-metrics.json'),source_summary_sha256=sha(source/'summary.json'),
            source_files_unchanged=all(sha(WORKSPACE/k)==v for k,v in hashes.items()),script_sha256=sha(Path(__file__))))
        print('Reused exact scored rows and closed160/40:',model)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('action',choices=['freeze','analyze']);ap.add_argument('--include-round2',action='store_true');a=ap.parse_args()
    freeze()if a.action=='freeze'else analyze(a.include_round2)
