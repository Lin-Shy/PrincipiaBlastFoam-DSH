"""Produce a factual manuscript insert only from closed objective snapshots."""
from pathlib import Path
import objective_experiment as exp

def main():
    strict_path=exp.OUT/'results/snapshot.json'
    alternate_path=exp.OUT/'supplementary_parser/results/snapshot.json'
    a=exp.read(strict_path);b=exp.read(alternate_path);dataset=exp.read(exp.DATA/'dataset.json')
    if any(s['status']!='closed' or s['completed']!=s['planned'] for s in (a,b)):
        raise ValueError('both scoring snapshots must be closed')
    if a['manifest_sha256']!=b['manifest_sha256'] or a['planned']!=b['planned']:
        raise ValueError('snapshot identity mismatch')
    def cfg(s,model,method):return next(x for x in s['configurations'] if x['model']==model and x['method']==method)
    def pair(model):return next(x for x in a['statistics']['paired'] if x['model']==model and x['comparison']=='bm25')
    def pct(x):return f'{100*x:.2f}'
    counts=dataset['types'];n=dataset['count']
    lines=[r'\subsection{客观题补充评测}',
        f'为补充可规则判分的证据，本文从同一版手册与案例构建{n}道客观题：填空{counts["fill"]}题、唯一解短问答{counts["short"]}题、单选{counts["single"]}题和判断{counts["judge"]}题。题目与原开放问答允许知识重叠，其中30道判断题与单选题共享事实；因此题数不等于独立知识点数。题目经本地AI辅助来源复核，未完成独立领域专家审核。',
        f'两种模型各使用九个主方法及四个消融，每配置{n}题，共{a["planned"]}个任务。8B采用超算Qwen3-8B部署，14B使用代理部署；部署不同于原开放问答的8B本地服务。生成侧仅接收题目、选项和检索资料，答案与评分规则仅在评分侧使用。',
        r'冻结规则要求最终答案中带有明确的FINAL标记；正确计1分，错误、格式不可解析和生成失败计0分，使用固定分母。整体准确率为主指标，题型宏平均和分题型结果作为辅助。依据资料章节或案例划分12个关联簇，以固定随机种子按簇进行10000次配对自助抽样，报告95\%区间；比较的$p$值采用簇级精确符号翻转检验，两个模型的16项主比较和8项消融分别进行Holm校正。该推断依赖簇间独立和零假设下簇差可交换，簇数有限，结果应谨慎解释。',
        r'\input{assets/objective_metrics.tex}',
        r'\begin{figure}[htbp]\centering',r'\includegraphics[width=0.95\textwidth]{assets/objective_main_accuracy.pdf}',
        r'\caption{客观题九种方法的冻结规则准确率和逐项95\%关联簇自助区间。}\label{fig:ch2-objective}',r'\end{figure}']
    for model,label in [('qwen3-8b','8B'),('qwen3-14b','14B')]:
        graph=cfg(a,model,'graph');bm=cfg(a,model,'bm25');comparison=pair(model)
        lines.append(f'{label}完整图和BM25的冻结规则准确率分别为{pct(graph["accuracy"])}\\%和{pct(bm["accuracy"])}\\%；完整图减BM25的差值为{pct(comparison["difference"])}个百分点，95\\%区间为$[{pct(comparison["ci95"][0])},{pct(comparison["ci95"][1])}]$个百分点，Holm校正后$p={comparison["holm_p"]:.4f}$。')
    alt8=cfg(b,'qwen3-8b','graph');alt14=cfg(b,'qwen3-14b','graph')
    lines += [f'在事后补充解析下，8B与14B完整图准确率分别为{pct(alt8["accuracy"])}\\%和{pct(alt14["accuracy"])}\\%；14B完整图在冻结规则下仅{cfg(a,"qwen3-14b","graph")["format_valid"]}份回答格式有效，因此冻结主结果受格式遵从显著限制。',
        '运行中发现，部分模型在最终JSON的答案字段中直接给出单行答案，未附规定标记。为分析格式约束的影响，本文事后增加统一补充解析：仅额外接受符合题型要求的完整单行答案，不从解释中猜测答案。该补充分析对所有模型、方法和题目一致应用，保留原冻结结果，不作为预注册主分析。',
        r'\input{assets/objective_parsing_comparison.tex}',
        '两种规则的差异同时反映格式遵从与可解析性，不能直接解释为领域知识质量的变化。客观题多数来自文档中的明确事实，部分单选干扰项较易排除；题目、知识来源和事后能力标签的关联限制了结论的外推。客观准确率与开放问答EAS分别报告，不合成为统一总分；本补充实验也不替代原裁判的独立人工审计。']
    target=exp.WORK/'graduation-thesis-materials/graduation-manuscript/docs/chap02_objective_results.tex'
    target.write_text('\n\n'.join(lines)+'\n',encoding='utf-8',newline='\n')
    exp.save(exp.OUT/'results/objective_manuscript_provenance.json',dict(strict_snapshot_sha256=exp.sha(strict_path),
        supplementary_snapshot_sha256=exp.sha(alternate_path),insert_sha256=exp.sha(target),code_sha256=exp.sha(Path(__file__))))
    print('objective manuscript insert generated')

if __name__=='__main__':main()
