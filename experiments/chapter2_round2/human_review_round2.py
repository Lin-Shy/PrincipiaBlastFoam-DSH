"""Blinded review of the new answers, using the previously fixed40-question sample.

No provider calls. Real human labels remain pending until supplied. Labels and
method keys must stay on the scoring side and never enter the knowledge corpus.
"""
import argparse
from collections import Counter,defaultdict
import statistics

from common import *
from human_review import kappa,weighted_kappa

GEN=ARCHIVE/'e2e_runs/answer14b_002'
OUT=ARCHIVE/'human_review_round2_001'

def export():
    old=ARCHIVE/'human_review'
    manifest=read(old/'sampling_manifest.json')
    forms=read(old/'blinded_answers.json');keys=read(old/'evaluation_only/method_key.json')
    if len(forms)!=80 or {f['question_id']for f in forms}!=set(manifest['question_ids']):raise ValueError('fixed human sample drift')
    oldkey={k['sample_id']:k for k in keys};newkeys=[];ratings=[]
    for form in forms:
        key=oldkey[form['sample_id']];path=GEN/key['arm']/'generation'/key['question_id']/'result.json'
        result=read(path)
        if result['id']!=key['question_id']or result['arm']!=key['arm']:raise ValueError('new answer identity mismatch')
        form.update(raw_answer=result['answer'],references=result['references'],generation_status=result['status'],review_status='pending')
        newkeys.append(dict(sample_id=form['sample_id'],question_id=key['question_id'],arm=key['arm'],
            answer_file=str(path.relative_to(WORKSPACE)),answer_sha256=sha(path),
            score_file=str((GEN/'scoring_001/sessions'/key['arm']/key['question_id']/'result.json').relative_to(WORKSPACE))))
        for reviewer in ['reviewer_1','reviewer_2']:
            ratings.append(dict(sample_id=form['sample_id'],reviewer_id=reviewer,review_status='pending',
                points=[dict(point_id=p['id'],label='',reason='')for p in form['required_points']],
                factuality='',factuality_reason='',applicability='',applicability_reason=''))
    if OUT.exists():raise FileExistsError('fresh review export required')
    save(OUT/'blinded_answers.json',forms);save(OUT/'ratings_template.json',ratings)
    save(OUT/'evaluation_only/method_key.json',newkeys)
    lines=['# 本轮80份原始回答盲审','',
        '沿用离线阶段预先固定的40题（四类各10题），每题本轮完整图与BM25各一份回答，共80份。没有按本轮成绩选题。',
        'R编号及展示顺序与此前抽样一致，但本包回答来自answer14b_002，不能用旧批次的人评替代。','',
        '两位评审独立阅读下列材料并各自填写ratings_template.json副本；不得查看evaluation_only或AI评分。',
        '覆盖：full=1，partial=0.5，omitted/wrong=0；unknown保留上下界。事实与条件分别判断pass/fail/unknown。',
        '人工不一致交第三人另行裁决；两位原始标注不可覆盖。题目审核不等于回答评分准确率。','']
    for f in forms:
        lines += [f"## {f['sample_id']} — {f['question_id']}",'',f['question'],'','### 原始回答','',f['raw_answer']or f"（生成状态：{f['generation_status']}）",'',
            '### 必要点与权重','']
        lines += [f"- {p['id']}（权重{p['weight']}）：{p['claim']}"for p in f['required_points']]
        lines += ['','### 适用条件与关键错误','',json.dumps(dict(applicability=f['applicability'],critical_errors=f['critical_errors']),ensure_ascii=False,indent=2),
            '','### 评分用原文','',json.dumps(f['evidence'],ensure_ascii=False,indent=2),'']
    (OUT/'review_packet.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    save(OUT/'manifest.json',dict(seed=manifest['seed'],questions=40,answers=80,reviewers=2,pending_records=160,
        old_sampling_sha256=sha(old/'sampling_manifest.json'),question_ids=manifest['question_ids'],
        generation_run='answer14b_002',selection='Fixed before new paid results; no selection by score',
        files={str(p.relative_to(OUT)):sha(p)for p in OUT.rglob('*')if p.is_file()},script_sha256=sha(Path(__file__))))
    (OUT/'README.md').write_text('# 本轮回答人工核验\n\n向两位评审分别提供review_packet.md或blinded_answers.json，以及各自的ratings_template.json副本。不要提供evaluation_only或AI标签。当前160条均pending，未宣称人工一致性或裁判准确率。\n\n图结构未改，50节点、50边、30别名抽查仍使用../human_review/中的待填表。\n\n回填后执行human_review_round2.py aggregate --ratings <真实标签文件> --output <全新报告目录名>。多份标签先合并为一个JSON数组；保留原始提交。\n',encoding='utf-8')
    print('Exported80 new blinded answers;160 actual human records pending')

def aggregate(path,output):
    forms={f['sample_id']:f for f in read(OUT/'blinded_answers.json')}
    keys={k['sample_id']:k for k in read(OUT/'evaluation_only/method_key.json')}
    ratings=read(path);accepted=[];seen=set();pending=0
    for rating in ratings:
        sid=rating['sample_id'];rid=rating['reviewer_id'];pair=(sid,rid)
        if sid not in forms or not rid.strip()or pair in seen:raise ValueError('unknown sample, missing reviewer or duplicate review')
        seen.add(pair)
        if rating['review_status']!='complete':pending+=1;continue
        f=forms[sid];pts=rating['points'];labels={p['point_id']:p['label']for p in pts};weights={p['id']:p['weight']for p in f['required_points']}
        if len(labels)!=len(pts)or set(labels)!=set(weights)or any(x not in ['full','partial','omitted','wrong','unknown']for x in labels.values()):raise ValueError('invalid point judgments')
        fact=rating['factuality'];app=rating['applicability']if f['conditional']else 'not_applicable'
        if fact not in ['pass','fail','unknown']or app not in (['pass','fail','unknown']if f['conditional']else ['not_applicable']):raise ValueError('invalid factuality or condition')
        lo=sum(weights[k]*{'full':1,'partial':.5}.get(v,0)for k,v in labels.items())/sum(weights.values())
        hi=lo+sum(weights[k]for k,v in labels.items()if v=='unknown')/sum(weights.values())
        lower=100*lo*(fact=='pass')*(app in ['pass','not_applicable']);upper=100*hi*(fact!='fail')*(app!='fail')
        if f['generation_status']!='answered':lower=upper=0
        accepted.append(dict(sample_id=sid,reviewer_id=rid,points=labels,factuality=fact,applicability=app,eas_lower=lower,eas_upper=upper))
    reviewers=sorted({r['reviewer_id']for r in accepted})
    if len(reviewers)>2:raise ValueError('at most2 primary reviewers; adjudication separate')
    paired=defaultdict(dict)
    for r in accepted:paired[r['sample_id']][r['reviewer_id']]=r
    pl=[];pr=[];fl=[];fr=[];al=[];ar=[]
    for sid,pair in paired.items():
        if len(pair)!=2:continue
        a,b=[pair[rid]for rid in reviewers]
        for pid in a['points']:pl.append(a['points'][pid]);pr.append(b['points'][pid])
        fl.append(a['factuality']);fr.append(b['factuality'])
        if forms[sid]['conditional']:al.append(a['applicability']);ar.append(b['applicability'])
    ai_comparisons=[];ai_by_reviewer={};mapping=dict(satisfied='full',partial='partial',omitted='omitted',contradicted='wrong',unknown='unknown')
    for rid in reviewers:
        hp=[];ap=[];hf=[];af=[];hc=[];ac=[];diffs=[]
        for r in [x for x in accepted if x['reviewer_id']==rid]:
            k=keys[r['sample_id']];source=WORKSPACE/k['answer_file']
            if sha(source)!=k['answer_sha256']:raise ValueError('blinded answer binding drift')
            s=read(WORKSPACE/k['score_file']);j=s.get('judgment')or{};m=s['metrics']
            ai={p['id']:mapping.get(p['verdict'],'unknown')for p in j.get('points',[])}
            for pid,v in r['points'].items():hp.append(v);ap.append(ai.get(pid,'unknown'))
            hf.append(r['factuality']);af.append(m['factuality'])
            if forms[r['sample_id']]['conditional']:hc.append(r['applicability']);ac.append(m['applicability'])
            lo,hi=ai_eas(m,forms[r['sample_id']]['conditional'])
            difference=dict(sample_id=r['sample_id'],reviewer_id=rid,human_minus_ai_eas_lower=r['eas_lower']-hi,human_minus_ai_eas_upper=r['eas_upper']-lo)
            ai_comparisons.append(difference);diffs.append(difference)
        ai_by_reviewer[rid]=dict(points=kappa(hp,ap),points_weighted=weighted_kappa(hp,ap),factuality=kappa(hf,af),condition=kappa(hc,ac),
            mean_human_minus_ai_eas_lower=statistics.mean(x['human_minus_ai_eas_lower']for x in diffs),mean_human_minus_ai_eas_upper=statistics.mean(x['human_minus_ai_eas_upper']for x in diffs))
    save(ARCHIVE/'reports'/output/'human_summary.json',dict(status='pending'if not accepted else 'partial'if len(accepted)!=160 else 'filled',
        expected_records=160,completed=len(accepted),submitted_pending=pending,missing_records=160-len(seen),paired_answers=sum(len(x)==2 for x in paired.values()),
        inter_human=dict(points=kappa(pl,pr),points_weighted=weighted_kappa(pl,pr),factuality=kappa(fl,fr),condition=kappa(al,ar)),
        ai_human=ai_by_reviewer or 'pending real human labels',ai_human_differences=ai_comparisons,ratings=accepted,
        boundary='Individual reviewer sensitivity, not adjudicated consensus; AI unknowns retained; no historical scores changed',
        input_sha256=sha(path),manifest_sha256=sha(OUT/'manifest.json'),script_sha256=sha(Path(__file__))))

def ai_eas(m,conditional):
    c=m['applicability'];f=m['factuality']
    return (100*m['required_point_coverage_lower']*(f=='pass')*((c=='pass')if conditional else True),
            100*m['required_point_coverage_upper']*(f!='fail')*((c!='fail')if conditional else True))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['export','aggregate']);p.add_argument('--ratings',type=Path);p.add_argument('--output')
    a=p.parse_args();export()if a.action=='export'else aggregate(a.ratings,a.output)
