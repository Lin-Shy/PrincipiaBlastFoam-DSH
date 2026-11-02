"""Re-score all responses using an explicitly supplementary parsing rule."""
import csv
import json
from collections import Counter
from pathlib import Path
import objective_experiment as exp
from objective_scoring_relaxed import score, VERSION
from objective_report import render

def main():
    manifest=exp.verify();source=exp.OUT/'scores/per_answer.json'
    old=exp.read(source);questions={q['id']:q for q in exp.read(exp.DATA/'model/questions.json')}
    gold={g['id']:g for g in exp.read(exp.DATA/'scoring/annotations.json')}
    out=exp.OUT/'supplementary_parser';rows=[]
    for original in old:
        r=dict(original);r['strict_score']=r['score'];r['strict_reason']=r['reason']
        if r['score'] is not None:
            raw=exp.read(exp.OUT/'generation'/r['config_id']/r['id']/'result.json')
            r.update(score(questions[r['id']],gold[r['id']],raw))
        else:r['parse_route']='pending';r['scoring_version']=VERSION
        rows.append(r)
    summaries=[]
    for config in manifest['configurations']:
        subset=[r for r in rows if r['config_id']==config['config_id']]
        complete=all(r['score'] is not None for r in subset)
        row=dict(config_id=config['config_id'],model=config['logical_model'],method=config['method_id'],
            planned=len(subset),completed=sum(r['score'] is not None for r in subset),
            answered=sum(r['generation_status']=='answered' for r in subset),
            correct=sum(r['score'] or 0 for r in subset),accuracy=sum(r['score'] or 0 for r in subset)/len(subset) if complete else None,
            format_valid=sum(r['format_valid'] is True for r in subset),tool_adoption=sum(r['tools']>0 for r in subset),
            prompt_tokens=sum(r['prompt_tokens'] for r in subset),completion_tokens=sum(r['completion_tokens'] for r in subset),seconds=sum(r['seconds'] for r in subset))
        for typ in ('fill','short','single','judge'):
            part=[r for r in subset if r['type']==typ]
            row[typ+'_accuracy']=sum(r['score'] or 0 for r in part)/len(part) if complete and part else None
        row['macro_accuracy']=sum(row[t+'_accuracy'] for t in ('fill','short','single','judge'))/4 if complete else None
        summaries.append(row)
    complete=all(r['score'] is not None for r in rows)
    snap=dict(updated=exp.now(),manifest_sha256=exp.sha(exp.MANIFEST),planned=manifest['tasks'],
        completed=sum(r['score'] is not None for r in rows),status='closed' if complete else 'in_progress',
        configurations=summaries,scoring_version=VERSION,source_strict_sha256=exp.sha(source),
        rule_sha256=exp.sha(Path(__file__).with_name('objective_scoring_relaxed.py')),
        parse_routes=dict(Counter(r['parse_route'] for r in rows)),
        interpretation='Supplementary, post hoc: additionally accepts only a single bare answer line. Strict frozen results retained separately.')
    if complete:
        from objective_statistics import analyze
        snap['statistics']=analyze(rows,manifest['analysis'])
    exp.save(out/'scores/per_answer.json',rows)
    exp.export_csv(out/'results/per_answer.csv',rows);exp.export_csv(out/'results/summary.csv',summaries)
    exp.save(out/'results/snapshot.json',snap)
    labels=exp.OUT/'analysis/capability_labels_v2.json'
    if labels.exists():exp.save(out/'analysis/capability_labels_v2.json',exp.read(labels))
    render(out,rows,snap)
    page=out/'results/index.html';html=page.read_text(encoding='utf8')
    html=html.replace('>开放问答结果</a>', '>冻结规则结果</a>')
    html=html.replace('<h1>第2章客观题实验</h1>',
        '<h1>第2章客观题：单行答案补充评分</h1><p>事后补充解析：在原标记规则之外接受无歧义单行答案。原冻结评分独立保留，不覆盖。</p>')
    page.write_text(html,encoding='utf8',newline='\n')
    print(json.dumps({k:snap[k] for k in ('status','planned','completed','parse_routes')},ensure_ascii=False),flush=True)

if __name__=='__main__':main()
