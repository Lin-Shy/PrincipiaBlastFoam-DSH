"""真实案例、历史QA与本轮固定查询分别标识；选择规则明确。"""
from common import *
from collections import defaultdict

def main(evaluation,output):
    summary_dir=ARCHIVE/'evaluation'/evaluation
    current={(r['method'],r['id'],r['budget']):r for r in read(summary_dir/'sessions.json')}
    historical={(r['arm'],r['id']):r for r in read(HISTORICAL/'analysis_001/session-metrics.json')}
    annotations={r['id']:r for r in read(DATASET/'scoring/annotations.json')}
    evidence=read(DATASET/'scoring/evidence.json')
    def now(m,q):return current.get((m,q,6000),{})
    rules=[
        ('multiple_nonconditional_complement','multiple & no condition; fixed-query graph all evidence, BM25 misses',
         lambda q:annotations[q]['labels']==dict(evidence_integration='multiple',condition_discrimination=False) and now('graph',q).get('all_evidence')==1 and now('bm25',q).get('all_evidence')==0),
        ('historical_condition_failure_after_evidence','historical graph condition fail despite historical complete evidence',
         lambda q:historical[('graph',q)]['conditional'] and historical[('graph',q)]['complete_necessary_evidence']==1 and historical[('graph',q)]['applicability']=='fail'),
        ('historical_bm25_better','historical BM25 EAS lower exceeds graph EAS upper',
         lambda q:historical[('bm25',q)]['score_lower']>historical[('graph',q)]['score_upper']),
        ('hybrid_below_bm25','fixed-query BM25+BGE recall below BM25 (fall back to explicitly labeled BM25+E5 if BGE not run)',
         lambda q:now('bm25_bge_m3' if ('bm25_bge_m3',q,6000) in current else 'bm25_e5',q).get('evidence_recall',0)<now('bm25',q).get('evidence_recall',0)),
        ('expansion_budget_displacement','fixed-query anchor-only complete evidence recall exceeds full graph under same budget',
         lambda q:now('anchor_only',q).get('evidence_recall',0)>now('graph',q).get('evidence_recall',0))]
    cases=[]
    for label,rule,predicate in rules:
        candidates=sorted(q for q in annotations if predicate(q))
        if not candidates:
            cases.append(dict(category=label,selection_rule=rule,status='no_matching_observed_case'));continue
        q=candidates[0];a=annotations[q]
        answers={}
        for method in ['graph','bm25']:
            path=HISTORICAL/'generation'/method/q/'result.json';value=read(path)
            answers[method]=dict(answer=value['answer'],references=value['references'],
                 metrics=historical[(method,q)],file_sha256=sha(path),
                 generation_batch='model14b_200_20261019_002; historical autonomous QA, not this fixed-query retrieval')
        current_rows={m:current[(m,q,6000)] for m in sorted({k[0] for k in current}) if (m,q,6000) in current}
        traces={m:read(ARCHIVE/'runs'/read(summary_dir/'summary.json')['run_id']/m/'traces'/(q+'.json')) for m in current_rows}
        cases.append(dict(category=label,selection_rule=rule,eligible_count=len(candidates),selection='lexicographically first eligible public question id; post-result explanatory case, not confirmatory sample',
            id=q,question=next(r['question'] for r in public_questions() if r['id']==q),labels=a['labels'],
            required_points=a['required_points'],registered_evidence={e:evidence[e] for e in a['required_evidence_ids']},
            historical_qa=answers,fixed_query_6000=current_rows,traces=traces))
    out=ARCHIVE/'reports'/output
    save(out/'cases.json',dict(evaluation_sha256=sha(summary_dir/'summary.json'),cases=cases,script_sha256=sha(Path(__file__))))
    lines=['# 可追溯案例（事后解释性选择）','','每类按明确条件选ID字典序第一题，保留未找到案例的类别。历史回答来自原14B批次；本轮固定查询没有新回答。两者不能当作同一条生成轨迹。','']
    for c in cases:
        lines += [f"## {c['category']}",'',f"规则：{c['selection_rule']}",'']
        if 'id' not in c:lines+=['无满足条件的实测案例，不构造原因。',''];continue
        lines += [f"{c['id']}：{c['question']}",'',f"满足条件题数：{c['eligible_count']}。",'',
                  '|方法|本轮6000字符登记证据召回|历史QA EAS下/上界|','|---|---:|---:|']
        for m,r in c['fixed_query_6000'].items():
            h=c['historical_qa'].get(m,{}).get('metrics')
            eas=f"{100*h['score_lower']:.2f}/{100*h['score_upper']:.2f}" if h else '本轮未生成'
            lines.append(f"|{m}|{r['evidence_recall']:.4f}|{eas}|")
        lines+=['','历史原始回答摘录：','']
        for m,v in c['historical_qa'].items():lines += [f"- {m}：{v['answer'][:600]}"]
        lines+=['','完整必要点、真实证据原文、来源哈希、全部候选及交付行段见cases.json；引用送达不等于语义蕴含。','']
    (out/'cases.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print([(c['category'],c.get('id',c.get('status'))) for c in cases])

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('--evaluation',required=True);p.add_argument('--output',required=True)
    a=p.parse_args();main(a.evaluation,a.output)
