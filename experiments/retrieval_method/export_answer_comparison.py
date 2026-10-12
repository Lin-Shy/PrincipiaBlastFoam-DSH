"""Export four selected, verbatim answer comparisons from existing frozen runs."""
import argparse
import hashlib
import json
from pathlib import Path

CASES = [
 ('UN01', '建筑阵列：局部改善', ['old_graph', 'graph'],
  '旧回答仅凭背景 blockMeshDict 推断案例没有建筑几何，依据不足；新回答明确区分 STL 建筑与背景网格，并承认不是九建筑现成模板。两版候选不同，不能归因于图谱本身。',
  ['并未包含任何建筑几何或3x3阵列。', '但该案例是L形建筑而非9个立方体建筑。']),
 ('UN05', '气体物性表：同预算下文件组更具体', ['files', 'graph'],
  '文件组指向实际的 constant/phaseProperties 和 TCoeffs；图谱组推测了该案例不存在的 system/thermophysicalProperties。图谱证据包已有部分 phaseProperties，却未正确用于回答。这里只比较配置定位，不能将文件组整篇回答视为完全正确。',
  ['该教程的 constant/phaseProperties 文件中包含了 thermodynamics 子字典，其中 TCoeffs 指定了温度表文件（如 constant/T.csv）', '因此您需要进一步查阅该教程的 system/thermophysicalProperties 文件以及相关文档']),
 ('UN06', '无反应颗粒：压缩遗漏依赖', ['old_graph', 'graph'],
  '旧回答提到 reacting 直径模型及曳力耦合；新版遗漏直径模型，并把颗粒反作用列为未知。新版还仅凭 defaultFieldValues 的零体积分数断言初始无颗粒，未考虑 regions 的覆盖。这是依赖覆盖退步，旧版建议也未经运行验证。',
  ['并相应调整颗粒直径模型（默认reacting直径模型与反应速率相关，应改为constant或其它非反应模型）。', '但需移除或禁用 massTransfer 中的 reactingParticle 模型，并设置合适的颗粒初始体积分数。']),
 ('UN08', '压力探针：证据已补齐，回答仍误用', ['text', 'graph'],
  '文本组承认未说明如何避免存整个流场；图谱组虽给出探针代码，却说无需修改整体输出设置。探针与全场输出各有控制项，开启探针不会自动减少全场写出；新增的输出控制关系未转化为完整指导。',
  ['未说明如何避免存储整个流场，但探针功能本身只记录指定点数据，不存储整个流场。', '您无需修改整体输出设置（如 writeControl 等），因为探测输出独立于流场输出。']),
]
LABELS = {'old_graph':'旧版：关键字＋图谱导航', 'text':'新版：纯文本', 'files':'新版：文件结构', 'graph':'新版：配置图谱'}
TEMPLATE = r'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>检索回答原文对比</title>
<style>*{box-sizing:border-box}body{margin:0;background:#eff3f8;color:#243751;font:15px/1.8 system-ui,sans-serif}header,main{max-width:1400px;margin:auto;padding:24px}h1{margin:0;font-size:26px}h2{font-size:20px}p{margin:8px 0}select{font:inherit;padding:9px;border:1px solid #cbd6e3;border-radius:6px;background:white;max-width:100%}.note{padding:16px;background:#e5eef9;border-left:4px solid #527db7;margin:18px 0}.grid{display:grid;grid-template-columns:1fr 1fr;gap:20px}article{padding:22px;background:white;border:1px solid #d9e1ec;border-radius:10px;min-width:0}.body{white-space:pre-wrap;overflow-wrap:anywhere}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px;background:#f5f7fa;padding:12px}summary{cursor:pointer}small,.meta{font-size:12px;color:#62758c;overflow-wrap:anywhere}.quote{white-space:pre-wrap;border-left:3px solid #97acc8;padding:10px;background:#f5f8fc}@media(max-width:800px){.grid{grid-template-columns:1fr}header,main{padding:14px}}</style>
<header><h1>检索回答 · 原文对比</h1><p>四道代表性问题，可切换旧版图谱与新版三种检索。原回答保留错误、引用和限制，评注单独列出。</p><small>使用已保存的实验输出；没有重新生成回答。旧版最多 6 轮检索、12,000 字符；新版单个证据包最多 6,000 字符、2 次模型调用。跨版差异包含预算和流程变化，不能单独归因于图谱。</small></header>
<main><select id="question" aria-label="问题"></select><h2 id="query"></h2><div class="note" id="review"></div><div class="grid"><article id="left"></article><article id="right"></article></div><p class="meta">这是开发集上的定性抽查，不是独立测试集排名。Token 为 API usage；新版各方法计入完整共享查询规划成本。</p></main>
<script type="application/json" id="data">__DATA__</script><script>
const data=JSON.parse(document.getElementById('data').textContent),$=id=>document.getElementById(id);function el(t,s){const n=document.createElement(t);if(s!==undefined)n.textContent=s;return n}for(const c of data.cases){const o=el('option',c.id+' · '+c.title);o.value=c.id;$('question').append(o)}
function panel(side,key,c){const p=$(side);p.replaceChildren();const select=el('select');select.setAttribute('aria-label',side==='left'?'左侧回答':'右侧回答');for(const [k,v] of Object.entries(c.variants)){const o=el('option',v.label);o.value=k;select.append(o)}select.value=key;select.onchange=()=>panel(side,select.value,c);p.append(select);const v=c.variants[key];p.append(el('p',v.tokens.toLocaleString()+' Token · '+v.calls+' 次模型调用'));const i=c.pair.indexOf(key);if(i>=0){const q=el('div','重点摘录：'+c.excerpts[i]);q.className='quote';p.append(q)}const body=el('div',v.answer.answer);body.className='body';p.append(el('h3','完整回答原文'),body);for(const k of ['references','unknowns','limitations']){const d=el('details');d.append(el('summary',k),el('pre',JSON.stringify(v.answer[k],null,2)));p.append(d)}const m=el('p','原记录：'+v.path+'\nSHA-256：'+v.sha256);m.className='meta';p.append(m)}
function render(){const c=data.cases.find(c=>c.id===$('question').value);$('query').textContent=c.query;$('review').textContent='审核评注（不是模型原文）：'+c.review;panel('left',c.pair[0],c);panel('right',c.pair[1],c)}$('question').onchange=render;render();window.answerComparison=data;
</script></html>'''


def export(archive, output):
    archive, output = Path(archive), Path(output)
    if output.exists() and any(output.iterdir()):
        raise ValueError('choose a new or empty output directory')
    cases = []
    for q, title, pair, review, excerpts in CASES:
        variants = {}
        for method, label in LABELS.items():
            relative = (f'complementarity_v1/run01/runs/{q}-text_graph.json' if method == 'old_graph'
                        else f'evidence_bundle_v1/run01/runs/{q}-{method}.json')
            raw = (archive / relative).read_bytes(); d = json.loads(raw)
            if method == 'old_graph':
                tokens = sum(e['response'].get('usage', {}).get('total_tokens', 0) for e in d['events'] if 'response' in e)
                calls = sum('response' in e for e in d['events'])
            else:
                tokens, calls = d['accounted_api_tokens'], 2
                query = d['query']
            assert isinstance(d['answer'], dict)
            variants[method] = dict(label=label, path=relative, sha256=hashlib.sha256(raw).hexdigest(),
                                    tokens=tokens, calls=calls, answer=d['answer'])
        for method, excerpt in zip(pair, excerpts):
            a = variants[method]['answer']
            assert excerpt in a['answer'] or any(excerpt in x for x in a['limitations'])
        cases.append(dict(id=q, title=title, query=query, pair=pair, review=review, excerpts=excerpts, variants=variants))
    data = dict(schema='verbatim-answer-comparison-v1', api_calls=0, cases=cases)
    output.mkdir(parents=True, exist_ok=True)
    (output/'comparison.json').write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n')
    embedded = json.dumps(data, ensure_ascii=False).replace('<', '\\u003c').replace('\u2028','\\u2028').replace('\u2029','\\u2029')
    (output/'answer-comparison.html').write_text(TEMPLATE.replace('__DATA__', embedded))
    md = ['# 四组实际回答对比\n', '以下摘录逐字取自已保存回答，完整回答、引用及限制见 [离线对比页](answer-comparison.html)。可切换四种输出。没有重新调用模型。\n', '旧版和新版的预算、提示及轮次不同，跨版只用于检查流程质量变化；新版三组共用规划和 6,000 字符上限。这是定性抽查，不是方法排名。\n']
    for c in cases:
        md += [f"## {c['id']}：{c['title']}\n", c['query']+'\n']
        for k, excerpt in zip(c['pair'], c['excerpts']):
            v = c['variants'][k]
            md += [f"**{v['label']}（{v['tokens']:,} Token）**\n", '> '+excerpt+'\n']
        md += ['**审核评注：** '+c['review']+'\n']
    (output/'具体回答对比.md').write_text('\n'.join(md))
    (output/'manifest.json').write_text(json.dumps({'api_calls':0, 'questions':4, 'original_answers':16,
        'files':{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in output.iterdir() if p.is_file()}},ensure_ascii=False,indent=2)+'\n')
    return {'questions':4, 'original_answers':16, 'api_calls':0}

if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--archive',required=True,type=Path);p.add_argument('--output',required=True,type=Path);a=p.parse_args();print(export(a.archive,a.output))
