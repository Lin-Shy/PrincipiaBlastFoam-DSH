"""Audit and export the explicitly authorized post-hoc source review."""
import csv, hashlib, html, json
from collections import Counter
from pathlib import Path
import objective_experiment as exp
import objective_review as review

def main():
    exp.verify();root=review.REVIEW;binding=exp.read(root/'manifest.json')
    if binding['questions_sha256']!=exp.sha(exp.DATA/'model/questions.json') or binding['annotations_sha256']!=exp.sha(exp.DATA/'scoring/annotations.json') or binding['code_sha256']!=exp.sha(Path(review.__file__)):
        raise ValueError('review input or implementation drift')
    questions=exp.read(exp.DATA/'model/questions.json');gold={g['id']:g for g in exp.read(exp.DATA/'scoring/annotations.json')}
    notes=exp.read(root/'analysis/flag_followup.json');follow={x['id']:x for x in notes['items']}
    rows=[];records=[];usage=Counter();verdicts=Counter()
    for q in questions:
        item=root/'items'/q['id'];r=exp.read(item/'review.json');req=exp.read(item/'requests/00.json')
        if req['status']!='response' or req['raw_response']['model']!=binding['deployment']['api_model_id']:
            raise ValueError('response or model mismatch '+q['id'])
        actual=req['request'];digest=hashlib.sha256(json.dumps(actual,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode('utf8')).hexdigest()
        if digest!=req['request_sha256']:raise ValueError('request hash mismatch '+q['id'])
        content=next(x['content'] for x in actual['messages'] if x['role']=='user')
        if content.endswith('\n/no_think'):content=content[:-len('\n/no_think')]
        if json.loads(content)!=review.packet(q,gold[q['id']]):raise ValueError('input mismatch '+q['id'])
        choice=req['raw_response']['choices'][0]
        if choice.get('finish_reason')!='stop' or json.loads(choice['message']['content'])!=r:raise ValueError('review response mismatch '+q['id'])
        if r['verdict'] not in ('valid','invalid','uncertain') or not isinstance(r['reason'],str):raise ValueError('review schema mismatch')
        for k,v in req['raw_response'].get('usage',{}).items():
            if type(v) is int:usage[k]+=v
        verdicts[r['verdict']]+=1;note=follow.get(q['id'],{})
        rows.append(dict(id=q['id'],type=q['type'],question=q['question'],options=json.dumps(q.get('options'),ensure_ascii=False),
            expected=gold[q['id']]['answer'],model_verdict=r['verdict'],model_reason=r['reason'],
            followup=note.get('assessment','not_flagged'),followup_reason=note.get('reason',''),
            evidence=json.dumps(gold[q['id']]['evidence'],ensure_ascii=False),input_tokens=req['raw_response']['usage']['prompt_tokens'],
            output_tokens=req['raw_response']['usage']['completion_tokens']))
        records.append(dict(id=q['id'],request_record_sha256=exp.sha(item/'requests/00.json'),review_sha256=exp.sha(item/'review.json')))
    invalid={x['id'] for x in rows if x['model_verdict']=='invalid'}
    if invalid!=set(follow):raise ValueError('follow-up coverage differs from model flags')
    out=root/'results';out.mkdir(parents=True,exist_ok=True)
    exp.export_csv(out/'reviews.csv',rows)
    snapshot=dict(status='closed',total=len(rows),model_verdicts=dict(verdicts),recorded_usage=dict(usage),
        followup_counts=dict(Counter(x['followup'] for x in rows)),review_model=binding['deployment']['api_model_id'],
        caveats=['事后AI复核，不是独立人工或领域专家审核。','复核模型与原实验8B模型同源，不能作为独立可靠性验证。',
                 '模型输出存在结论与理由矛盾，不以valid自动证明题目正确。','题目和标准答案已发送该服务，未来使用相同服务进行评测需考虑潜在暴露。',
                 '复核不修改冻结题库、主实验响应或分数；两项措辞与技术边界建议领域专家核查。'],
        questions_sha256=binding['questions_sha256'],annotations_sha256=binding['annotations_sha256'],
        private_manifest_sha256=exp.sha(root/'manifest.json'),review_code_sha256=binding['code_sha256'],
        followup_sha256=exp.sha(root/'analysis/flag_followup.json'),records=records,report_code_sha256=exp.sha(Path(__file__)))
    exp.save(out/'snapshot.json',snapshot)
    data=json.dumps(dict(rows=rows,snapshot=snapshot),ensure_ascii=False).replace('<','\\u003c')
    page='''<!doctype html><html lang="zh"><meta charset="utf-8"><title>客观题事后来源复核</title>
<style>body{font:16px system-ui;max-width:1200px;margin:30px auto;background:#f5f7fa;color:#172333}article{background:white;padding:18px;margin:12px 0}pre{white-space:pre-wrap;word-break:break-word}input,select,button{padding:8px}a{color:#1756a9}</style>
<h1>客观题事后 AI 来源复核</h1><p><a href="../../objective200/results/index.html">客观题实验</a> · <a href="reviews.csv">逐题 CSV</a> · <a href="snapshot.json">审计快照</a></p><div id="status"></div><div id="caveats"></div><select id="verdict"><option value="">全部模型判断</option><option value="valid">valid</option><option value="invalid">invalid</option><option value="uncertain">uncertain</option></select><input id="query" placeholder="搜索题号或题目"><button id="prev">上一页</button><button id="next">下一页</button><span id="count"></span><div id="items"></div>
<script>const DATA=__DATA__;const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));const s=DATA.snapshot;document.querySelector('#status').textContent=`${s.total}题 · 模型有效 ${s.model_verdicts.valid||0} / 有疑点 ${s.model_verdicts.invalid||0} / 不确定 ${s.model_verdicts.uncertain||0}`;document.querySelector('#caveats').innerHTML='<ul>'+s.caveats.map(x=>'<li>'+esc(x)+'</li>').join('')+'</ul>';let page=0;function show(){let v=document.querySelector('#verdict').value,q=document.querySelector('#query').value.toLowerCase();let rows=DATA.rows.filter(r=>(!v||r.model_verdict===v)&&(r.id+' '+r.question).toLowerCase().includes(q));page=Math.max(0,Math.min(page,Math.ceil(rows.length/20)-1));document.querySelector('#count').textContent=`共 ${rows.length} 条，第 ${page+1} 页`;document.querySelector('#items').innerHTML=rows.slice(page*20,page*20+20).map(r=>`<article><b>${esc(r.id)} · 模型：${esc(r.model_verdict)} · 跟进：${esc(r.followup)}</b><pre>${esc(r.question)}\n${esc(r.options)}\n标准答案：${esc(r.expected)}</pre><p>模型理由：${esc(r.model_reason)}</p><p>事后来源跟进：${esc(r.followup_reason||'未被模型标记，不代表人工复核')}</p><details><summary>评分侧来源</summary><pre>${esc(r.evidence)}</pre></details></article>`).join('')};document.querySelector('#verdict').onchange=()=>{page=0;show()};document.querySelector('#query').oninput=()=>{page=0;show()};document.querySelector('#prev').onclick=()=>{page--;show()};document.querySelector('#next').onclick=()=>{page++;show()};show();</script></html>'''
    (out/'index.html').write_text(page.replace('__DATA__',data),encoding='utf8',newline='\n')
    print(json.dumps({'total':len(rows),'verdicts':dict(verdicts),'followup':snapshot['followup_counts'],'usage':dict(usage)},ensure_ascii=False))

if __name__=='__main__':main()
