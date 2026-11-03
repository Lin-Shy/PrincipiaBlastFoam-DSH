"""Produce thesis insert and figure solely from the closed strict JSON snapshot."""
from pathlib import Path
import shutil
import matplotlib.pyplot as plt
import figure_style as style
import objective_experiment as exp
import objective_json_full as full


def main():
    path = full.OUT / 'results/snapshot.json'
    snap = exp.read(path)
    if snap['status'] != 'closed' or snap['completed'] != snap['planned'] or snap['planned'] != 4472:
        raise ValueError('Full fixed-denominator snapshot must be closed')
    rows = snap['configurations']
    stats = snap['statistics']
    work = exp.WORK / 'graduation-thesis-materials'
    manuscript = work / 'graduation-manuscript'
    assets = manuscript / 'assets'
    def cfg(model, method):
        return next(r for r in rows if r['model'] == model and r['method'] == method)
    def pair(model):
        return next(x for x in stats['paired'] if x['model'] == model and x['comparison'] == 'bm25')
    def pct(x):
        return f'{x * 100:.2f}'
    style.setup()
    fig, axes = plt.subplots(1, 2, figsize=(7.2, 4.1), sharey=True)
    for ax, model in zip(axes, ('qwen3-8b', 'qwen3-14b')):
        for i, method in enumerate(style.MAIN):
            r = cfg(model, method)
            lo, hi = stats['ci95'][r['config_id']]
            ax.plot([100 * lo, 100 * hi], [i, i], color=style.MODEL_COLORS[model])
            ax.plot(100 * r['accuracy'], i, 'o', color=style.MODEL_COLORS[model])
        ax.set_yticks(range(len(style.MAIN)), [style.NAMES[x] for x in style.MAIN])
        ax.invert_yaxis(); ax.set_xlim(0, 100); ax.set_title(model); ax.set_xlabel('客观题准确率（%）')
    style.save(fig, full.OUT / 'results/figures', 'objective_main_accuracy')
    shutil.copyfile(full.OUT / 'results/figures/objective_main_accuracy.pdf', assets / 'objective_main_accuracy.pdf')
    lines = [r'\begin{table}[htbp]\centering\footnotesize',
             r'\caption{客观题准确率及题型分项（每配置固定分母）}\label{tab:ch2-objective}',
             r'\begin{tabular}{llrrrrrr}\toprule', r'模型 & 方法 & 完成 & 总体 & 填空 & 短答 & 单选 & 判断 \\ \midrule']
    for model in ('qwen3-8b', 'qwen3-14b'):
        for method in style.NAMES:
            r = cfg(model, method)
            vals = [r[x] for x in ('accuracy', 'fill_accuracy', 'short_accuracy', 'single_accuracy', 'judge_accuracy')]
            lines.append(model.replace('-', r'\mbox{-}') + ' & ' + style.NAMES[method] + ' & '
                         + str(r['completed']) + '/' + str(r['planned']) + ' & '
                         + ' & '.join(f'{100 * x:.1f}' for x in vals) + r' \\')
    lines.extend([r'\bottomrule\end{tabular}', r'\end{table}'])
    (assets / 'objective_metrics.tex').write_text('\n'.join(lines) + '\n', encoding='utf8')
    text = [r'\subsection{客观题补充评测}',
        '从同一版手册与案例构建172道客观题：填空60、唯一解短答32、单选50和判断30。30组单选与判断共享事实，题目与开放问答允许知识重叠；题目数量不等于独立事实数。题目经过AI辅助来源复核，未完成独立领域专家审核。',
        '两种模型各使用九种主方法及四项消融，每配置172题，共4472项任务；8B使用超算服务，14B使用代理。每轮输出遵守工具动作与最终JSON协议，最终对象的answer字段仅填写答案，评分程序核查原始JSON并拒绝重复字段、冲突或无效答案。生成失败按零分计入固定分母。',
        '实际实验前对20题、两种模型及三种方法进行了格式试验；成功生成中的有效格式率分别为98.04\\%与96.67\\%。试验题与正式题重叠，结果仅支持格式可行性，不是独立知识测试。原题答案在此次正式重跑之前曾发给8B服务作来源复核，因此8B结果有潜在材料暴露风险。',
        '整体准确率为主指标；按12个资料关联簇进行10000次配对自助抽样，报告95\\%区间。两模型16项主比较和8项消融比较分别进行Holm校正。簇数有限，统计结论依赖簇间独立与符号翻转假设，应谨慎解释。',
        r'\input{assets/objective_metrics.tex}',
        r'\begin{figure}[htbp]\centering', r'\includegraphics[width=0.95\textwidth]{assets/objective_main_accuracy.pdf}',
        r'\caption{客观题主方法准确率和逐项95\%关联簇自助区间。}\label{fig:ch2-objective}', r'\end{figure}']
    for model, label in [('qwen3-8b', '8B'), ('qwen3-14b', '14B')]:
        g, b, p = cfg(model, 'graph'), cfg(model, 'bm25'), pair(model)
        text.append(f'{label}完整图与BM25准确率分别为{pct(g["accuracy"])}\\%和{pct(b["accuracy"])}\\%；完整图减BM25为{pct(p["difference"])}个百分点，95\\%区间为$[{pct(p["ci95"][0])},{pct(p["ci95"][1])}]$个百分点，Holm校正后$p={p["holm_p"]:.4f}$。')
    text.append('客观准确率与开放问答EAS分别报告，不合成为统一总分；本实验不能替代开放问答裁判的独立人工审计。')
    (manuscript / 'docs/chap02_objective_results.tex').write_text('\n\n'.join(text) + '\n', encoding='utf8')
    exp.save(full.OUT / 'results/publish_provenance.json', dict(snapshot_sha256=exp.sha(path),
        manuscript_sha256=exp.sha(manuscript / 'docs/chap02_objective_results.tex'),
        table_sha256=exp.sha(assets / 'objective_metrics.tex'), figure_sha256=exp.sha(assets / 'objective_main_accuracy.pdf'),
        script_sha256=exp.sha(Path(__file__))))
    print('JSON objective manuscript assets generated')


if __name__ == '__main__':
    main()
