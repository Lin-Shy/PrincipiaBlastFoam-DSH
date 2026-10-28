"""Unclosed result entry: one statistical snapshot and uniform missing-score bounds."""
import csv
from html import escape
import single_pass_dev40 as s
from figure_style import NAMES


def run():
    out=s.RUN/'results'
    rows=list(csv.DictReader((out/'tables/draft_scorecard.csv').open(encoding='utf-8-sig')))
    assert len(rows)==32 and all(r['EAS_arith'].startswith('[') and r['EAS_geo'].startswith('[') for r in rows)
    h=['<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>Test160 未闭合结果</title>',
       '<style>body{font:15px system-ui;max-width:1200px;margin:32px auto;padding:0 20px;color:#20334b}table{border-collapse:collapse;width:100%}td,th{padding:8px;border-bottom:1px solid #dfe6ed;text-align:right}td:first-child,th:first-child{text-align:left}img{max-width:100%}aside{padding:16px;background:#edf4f8}</style>',
       '<h1>第2章Test160：评分未闭合</h1>',
       '<aside>双裁判为GPT-6 Sol（gpt-6-sol）与DeepSeek V4.1 Flash（deepseek-v4.1-flash），沿用冻结配置、Prompt与五档评分规则。原人工审计未达到预设严格门槛，评分闭合前不发布最终结果。</aside>',
       '<p>下表与论文使用同一统计快照：5120生成终态、4989有效回答、131正式失败、2322份双评完成、2667份缺双评。后台新增评分尚未并入。所有方法统一展示缺评识别上下界[L,U]；完整配置L=U。这些界限不是95%置信区间。</p>',
       '<p><a href="../test160_runs/closure_audit.json">最新原始记录核验</a> · <a href="../test160_runs/resume_gpt_sol_status.json">Sol运行状态</a> · <a href="../test160_runs/resume_deepseek_flash_status.json">DeepSeek运行状态</a></p>',
       '<p><a href="tables/draft_scorecard.csv">32配置表</a> · <a href="tables/per_answer.csv">5120逐题快照</a> · <a href="tables/paired_comparisons.csv">配对统计</a> · <a href="manuscript_snapshot.json">快照哈希</a> · <a href="../release/protocol/figure_style.md">图表规范</a></p>',
       '<table><tr><th>模式/模型/方法</th><th>EAS算术</th><th>EAS几何</th><th>双评缺口</th><th>状态</th></tr>']
    for r in rows:
        name=('自主' if r['mode']=='agentic' else '单次')+' / '+r['model']+' / '+NAMES[r['method']]
        status='已完成' if int(r['missing_dual'])==0 else '待补'
        h.append('<tr>'+''.join('<td>'+escape(str(x))+'</td>' for x in [name,r['EAS_arith'],r['EAS_geo'],r['missing_dual'],status])+'</tr>')
    h.append('</table><p>图表均来自上述统计快照，新增评分闭合后须统一重算。</p>')
    for name in ['backend_evidence','main_bounds','type_scores','ablation_bounds','mode_bounds','tool_adoption']:
        h.append('<p><a href="figures/draft_'+name+'.pdf">矢量PDF</a><br><img src="figures/draft_'+name+'.svg" alt="'+name+'"></p>')
    h.append('</html>')
    (out/'index.html').write_text('\n'.join(h),encoding='utf-8')


if __name__=='__main__':run()
