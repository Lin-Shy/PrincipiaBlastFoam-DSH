"""K/F/A diagnostics from the exact manuscript snapshot, excluding live recovery."""
import csv
import hashlib
import json
from pathlib import Path
import shutil
import statistics

import numpy as np
import matplotlib.pyplot as plt
import figure_style as st
import single_pass_dev40 as s

RESULTS = s.RUN / 'results'
ASSETS = s.WORKSPACE / 'graduation-thesis-materials/graduation-manuscript/assets/chapter2_test160'
JUDGES = ('gpt_sol', 'deepseek_flash')
FACTORS = ('K', 'F', 'A')


def read(p):
    return json.loads(p.read_text(encoding='utf-8-sig'))


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def numeric(v):
    return type(v) in (int, float)


def interval(row, factor, judge=None):
    assert not row['generation_failed'] and (factor != 'A' or row['conditional'])
    if judge is None:
        pairs = [interval(row, factor, j) for j in JUDGES]
        return [statistics.mean(p[side] for p in pairs) for side in (0, 1)]
    metrics = row['score']['by_judge'][judge]
    if factor == 'K':
        return metrics['coverage_bounds']
    value = metrics[factor]
    return [value, value] if numeric(value) else [0., 1.]


def writecsv(name, rows):
    with (RESULTS / 'tables' / name).open('w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def fmt(pair):
    return '[' + ', '.join(f'{x:.2f}' for x in pair) + ']'


def main():
    snapshot = read(RESULTS / 'manuscript_snapshot.json')
    for rel, expected in snapshot['statistical_source_hashes'].items():
        assert sha(s.WORKSPACE / rel) == expected, 'Manuscript snapshot drift: ' + rel
    source = RESULTS / 'test160_results.json'
    data = read(source)
    rows = data['per_answer']
    lookup = {tuple(r[k] for k in ('mode', 'model', 'method', 'question_id')): r for r in rows}
    assert len(rows) == len(lookup) == 5120
    assert sum(not r['generation_failed'] and r['evaluation_complete'] for r in rows) == snapshot['dual_valid']
    # The rich JSON is usable only after every score is checked against the bound CSV.
    csvrows = list(csv.DictReader((RESULTS / 'tables/per_answer.csv').open(encoding='utf-8-sig')))
    for flat in csvrows:
        r = lookup[tuple(flat[k] for k in ('mode', 'model', 'method', 'question_id'))]
        assert r['source_sha256'] == flat['source_sha256']
        for judge in JUDGES:
            for factor in (*FACTORS, 'EAS_arith', 'EAS_geo'):
                v = r['score']['by_judge'][judge][factor]
                saved = flat[judge + '_' + factor]
                assert (v is None and not saved) or str(v) == saved or (numeric(v) and abs(v - float(saved)) < 1e-10)
        for metric in ('EAS_arith', 'EAS_geo'):
            assert np.allclose(r['score']['bounds'][metric], json.loads(flat[metric + '_bounds']))
    per_answer = []
    groups = []
    disparities = []
    for group in data['groups']:
        key = tuple(group[k] for k in ('mode', 'model', 'method'))
        all_rows = [r for r in rows if tuple(r[k] for k in ('mode', 'model', 'method')) == key]
        assert len(all_rows) == 160
        answered = [r for r in all_rows if not r['generation_failed']]
        out = dict(zip(('mode', 'model', 'method'), key))
        out.update(planned_n=160, answered_n=len(answered), generation_failures=160-len(answered),
                   conditional_answered_n=sum(r['conditional'] for r in answered))
        for factor in FACTORS:
            eligible = [r for r in answered if factor != 'A' or r['conditional']]
            pairs = [interval(r, factor) for r in eligible]
            out[factor + '_n'] = len(eligible)
            out[factor + '_known_n'] = sum(abs(p[1]-p[0]) < 1e-12 for p in pairs)
            out[factor + '_bounds'] = [100*statistics.mean(p[i] for p in pairs) for i in (0, 1)]
            common = [r for r in eligible if all(numeric(r['score']['by_judge'][j][factor]) for j in JUDGES)]
            delta = [100*(r['score']['by_judge'][JUDGES[0]][factor]-r['score']['by_judge'][JUDGES[1]][factor]) for r in common]
            disparities.append(dict(mode=key[0], model=key[1], method=key[2], factor=factor,
                                    applicable_answered_n=len(eligible), paired_known_n=len(common),
                                    gpt_minus_deepseek=statistics.mean(delta) if delta else None,
                                    mean_absolute_difference=statistics.mean(map(abs, delta)) if delta else None))
            for r, p in zip(eligible, pairs):
                per_answer.append(dict(mode=key[0], model=key[1], method=key[2], question_id=r['question_id'],
                                       factor=factor, lower=100*p[0], upper=100*p[1],
                                       gpt_sol=r['score']['by_judge']['gpt_sol'][factor],
                                       deepseek_flash=r['score']['by_judge']['deepseek_flash'][factor]))
        groups.append(out)
    writecsv('snapshot_factor_per_answer.csv', per_answer)
    flatgroups = [{k: json.dumps(v) if isinstance(v, list) else v for k, v in g.items()} for g in groups]
    writecsv('snapshot_factor_summary.csv', flatgroups)
    writecsv('snapshot_factor_judge_differences.csv', disparities)
    decomposition = []
    for baseline in ('bm25', 'e5'):
        selected = [r for r in rows if (r['mode'], r['model'], r['method']) == ('agentic', 'qwen3-14b', 'graph')]
        contributions = {f: [] for f in FACTORS}
        eas = []
        for left in selected:
            right = lookup[('agentic', 'qwen3-14b', baseline, left['question_id'])]
            assert not left['generation_failed'] and not right['generation_failed']
            d = 3 if left['conditional'] else 2
            for factor in FACTORS:
                if factor == 'A' and not left['conditional']:
                    contributions[factor].append(0.)
                    continue
                a, b = interval(left, factor), interval(right, factor)
                assert a[0] == a[1] and b[0] == b[1]
                contributions[factor].append(100*(a[0]-b[0])/d)
            eas.append(left['score']['composite']['EAS_arith']-right['score']['composite']['EAS_arith'])
        result = dict(model='qwen3-14b', mode='agentic', left='graph', right=baseline, n=160,
                      **{f: statistics.mean(v) for f, v in contributions.items()},
                      EAS_arith_difference=statistics.mean(eas))
        assert abs(sum(result[f] for f in FACTORS)-result['EAS_arith_difference']) < 1e-10
        decomposition.append(result)
    writecsv('snapshot_factor_eas_decomposition.csv', decomposition)
    ASSETS.mkdir(parents=True, exist_ok=True)

    def table(path, caption, label, own, long=False):
        lines = [r'\begingroup\footnotesize\setlength{\tabcolsep}{3pt}']
        if long:
            lines += [r'\begin{longtable}{llrrrrr}', r'\caption{'+caption+r'}\label{'+label+r'}\\']
        else:
            lines += [r'\begin{table}[htbp]\centering', r'\caption{'+caption+r'}\label{'+label+'}', r'\begin{tabular}{llrrrr}']
        header = r'配置 & 模型 & $n/c$ & $100K$ & $100F$ & $100A$' + (r' & 已知数$K/F/A$' if long else '') + r' \\'
        lines += [r'\toprule', header, r'\midrule']
        if long:
            lines += [r'\endfirsthead\toprule', header, r'\midrule\endhead']
        for g in own:
            cells = [st.NAMES[g['method']]+'/'+('单次' if g['mode']=='single_pass' else '自主'), g['model'].replace('qwen3-', ''),
                     f"{g['answered_n']}/{g['conditional_answered_n']}"]
            cells[1] = cells[1].upper()
            cells += [fmt(g[f+'_bounds']) for f in FACTORS]
            if long:
                cells += ['/'.join(str(g[f+'_known_n']) for f in FACTORS)]
            lines.append(' & '.join(cells)+r' \\')
        lines += [r'\bottomrule', r'\end{longtable}' if long else r'\end{tabular}\end{table}', r'\endgroup']
        (ASSETS/path).write_text('\n'.join(lines)+'\n', encoding='utf-8')
    core = [g for g in groups if g['method'] in ('graph', 'bm25', 'bge_m3')]
    table('draft_factors.tex', '三个后端两种模式的分项评分：同一统计快照，括号内为识别边界', 'tab:ch2-factors', core)
    table('draft_factors_all.tex', '32个配置的K/F/A分项与评分识别情况', 'tab:ch2-factors-all', groups, True)
    types = []
    for typ, name in [('S0','单资料非条件'), ('S1','单资料条件'), ('M0','多资料非条件'), ('M1','多资料条件')]:
        own = [r for r in rows if (r['mode'],r['model'],r['method'],r['type']) == ('agentic','qwen3-14b','graph',typ)]
        assert len(own) == 40 and all(not r['generation_failed'] for r in own)
        types.append(dict(type=typ,name=name,n=40,**{f:100*statistics.mean(interval(r,f)[0] for r in own) if f!='A' or own[0]['conditional'] else None for f in FACTORS}))
    writecsv('snapshot_factor_types.csv', types)
    lines = [r'\begin{table}[htbp]\centering\footnotesize',
             r'\caption{14B完整图自主模式的题型分项：每类40题，均已双评}\label{tab:ch2-factor-types}',
             r'\begin{tabular}{lrrr}\toprule 题型 & $100K$ & $100F$ & $100A$ \\ \midrule']
    for row in types:
        lines.append(row['name']+' & '+' & '.join('--' if row[f] is None else f'{row[f]:.2f}' for f in FACTORS)+r' \\')
    lines += [r'\bottomrule\end{tabular}\end{table}']
    (ASSETS/'draft_factor_types.tex').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    font = st.setup()
    fig, axes = plt.subplots(1, 2, figsize=(7.1, 3.0))
    x = np.arange(3)
    for i, method in enumerate(('graph', 'bm25', 'e5')):
        g = next(g for g in groups if (g['mode'], g['model'], g['method']) == ('agentic', 'qwen3-14b', method))
        values = [g[f+'_bounds'][0] for f in FACTORS]
        axes[0].bar(x+(i-1)*.25, values, width=.25, color=st.COLORS[method], label=st.NAMES[method])
    axes[0].set(xticks=x, xticklabels=['覆盖K', '事实F', '条件A'], ylim=(0,100), ylabel='分项均值 × 100', title='14B自主模式：分项质量')
    axes[0].legend(loc='upper center', ncol=3, fontsize=7)
    colors = plt.get_cmap(st.CMAP)([.12, .5, .88])
    for i, factor in enumerate(FACTORS):
        values = [r[factor] for r in decomposition]
        bars = axes[1].bar(np.arange(2)+(i-1)*.25, values, width=.25, color=colors[i], label=factor)
        axes[1].bar_label(bars, fmt='%.2f', fontsize=7, padding=2)
    axes[1].set(xticks=range(2), xticklabels=['图减BM25', '图减E5'], ylabel='对EAS算术差的贡献（分）', title='逐题线性分解（160题）')
    axes[1].set_ylim(0, max(r[f] for r in decomposition for f in FACTORS)*1.25)
    axes[1].legend(ncol=3, loc='upper right')
    for ax in axes:
        ax.grid(axis='y', alpha=.18)
        ax.set_axisbelow(True)
    st.save(fig, RESULTS/'figures', 'draft_factor_diagnostics')
    for ext in ('pdf', 'svg', 'png'):
        shutil.copyfile(RESULTS/'figures'/('draft_factor_diagnostics.'+ext), ASSETS/('draft_factor_diagnostics.'+ext))
    outputs = [RESULTS/'tables'/n for n in ('snapshot_factor_per_answer.csv', 'snapshot_factor_summary.csv', 'snapshot_factor_judge_differences.csv', 'snapshot_factor_eas_decomposition.csv', 'snapshot_factor_types.csv')]
    outputs += list(ASSETS.glob('draft_factor*'))
    report = dict(status='provisional_snapshot_diagnostics', background_recovery_excluded=True,
                  snapshot_dual_valid=snapshot['dual_valid'], generation_tasks=5120,
                  units='K/F/A multiplied by 100; interval endpoints, not confidence intervals',
                  denominator='All answered tasks for K/F, answered conditional tasks for A; failures remain separate and EAS keeps 160 tasks',
                  per_answer_comparison_to_bound_csv_passed=True, font=font,
                  groups=groups, judge_disparities=disparities, eas_arithmetic_decomposition=decomposition,
                  source_hashes={str(p.relative_to(s.WORKSPACE)):sha(p) for p in [source, RESULTS/'manuscript_snapshot.json', RESULTS/'tables/per_answer.csv', Path(__file__), Path(st.__file__)]},
                  output_hashes={str(p.relative_to(s.WORKSPACE)):sha(p) for p in outputs})
    s.save(RESULTS/'factor_analysis_provenance.json', report)
    print(json.dumps(dict(groups=len(groups), decomposition=decomposition,
                         completed_14b_judge_differences=[r for r in disparities if r['mode']=='agentic' and r['model']=='qwen3-14b' and r['method'] in ('graph','bm25','e5')]), ensure_ascii=False))


if __name__ == '__main__':
    main()
