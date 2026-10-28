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
       '<aside>GPT候选接口为gpt-6.1-terra；统一替换须先通过固定人工参考验证并完成真实重评。当前验证存在传输未决，尚未通过验收，正式Terra继续调用已暂停。既有Sol评分保留原身份，原审计失败事实保留。<a href="../evaluation/judges/terra_validation/index.html">Terra验证结果</a> · <a href="../release/protocol/test160_gpt_terra_amendment.json">接口变更记录</a>。</aside>',
       '<p>下表与论文使用同一切换前统计快照：5120生成终态、4989有效回答、131正式失败、2322份双评完成、2667份缺双评。后台新增评分尚未并入。所有方法统一展示缺评识别上下界[L,U]；完整配置L=U。这些界限不是95%置信区间。</p>',
       '<p><a href="../test160_runs/closure_audit.json">最新原始记录核验</a> · <a href="../test160_runs/resume_gpt_terra_status.json">Terra实时状态</a> · <a href="../test160_runs/resume_deepseek_flash_status.json">DeepSeek实时状态</a> · <a href="model_migration_update.txt">本次更新说明</a></p>',
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
