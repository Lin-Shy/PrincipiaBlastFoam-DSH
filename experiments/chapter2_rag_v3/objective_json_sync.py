"""Synchronize thesis summary and research design after audited JSON closure."""
import re
from pathlib import Path
import objective_experiment as exp
import objective_json_full as full


def replace_once(text, pattern, replacement):
    result, n = re.subn(pattern, lambda _: replacement, text, count=1, flags=re.S)
    if n != 1:
        raise ValueError('Missing expected marker: ' + pattern)
    return result


def main():
    snapshot_path = full.OUT / 'results/snapshot.json'
    audit = exp.read(full.OUT / 'results/json_audit.json')
    s = exp.read(snapshot_path)
    if audit.get('status') != 'passed' or audit.get('snapshot_sha256') != exp.sha(snapshot_path) or s['status'] != 'closed':
        raise ValueError('A closed and audited matching snapshot is required')
    def graph(model):
        return next(r for r in s['configurations'] if r['model'] == model and r['method'] == 'graph')
    a, b = (f'{100 * graph(m)["accuracy"]:.2f}' for m in ('qwen3-8b', 'qwen3-14b'))
    root = exp.WORK / 'graduation-thesis-materials'
    ms = root / 'graduation-manuscript'
    edits = {}
    p = ms / 'docs/abstract.tex'; t = p.read_text(encoding='utf8')
    t = replace_once(t, r'% OBJECTIVE-20261102-BEGIN.*?% OBJECTIVE-20261102-END',
        '% OBJECTIVE-20261102-BEGIN\n客观题172道、4472项任务；严格JSON答案字段评分下完整图准确率8B为'+a+r'\%、14B为'+b+r'\%。题目共享事实且未经独立专家审核；8B服务先前收到答案，存在潜在材料暴露。'+'\n% OBJECTIVE-20261102-END')
    t = replace_once(t, r'(?m)^On 172 objective items,[^\r\n]*$',
        'On 172 objective items, graph accuracy under strict JSON scoring is '+a+r'\% (8B) and '+b+r'\% (14B). Some facts recur; expert review is pending and prior answer exposure limits 8B inference.')
    edits[p] = t
    p = ms / 'docs/chap05.tex'; t = p.read_text(encoding='utf8')
    t = replace_once(t, r'客观题补充评价覆盖172题和4472个任务，[^\r\n]*',
        '客观题补充评价覆盖172题和4472个任务，严格JSON答案字段规则下8B和14B完整图准确率分别为'+a+r'\%与'+b+r'\%。客观准确率与开放问答EAS分别解释；题目共享事实且缺少独立领域专家复核，8B服务先前收到答案的潜在暴露限制其结果解释。')
    edits[p] = t
    p = ms / 'docs/appendix_ch02.tex'; t = p.read_text(encoding='utf8')
    t = replace_once(t, r'% OBJECTIVE-20261102-BEGIN.*?% OBJECTIVE-20261102-END',
        '% OBJECTIVE-20261102-BEGIN\n\\section{客观题补充实验的来源与审计}\n'
        '严格JSON批次位于\\path{graduation-experiment-results/chapter2_retrieval/objective_json_v2/full/}。'
        '\\path{results/per_answer.csv}、\\path{results/summary.csv}、\\path{results/snapshot.json}'
        '分别记录逐答、配置汇总与统计；\\path{results/json_audit.json}绑定逐项重评分和统计重建。'
        '原始请求保留在本地，可能含服务端点。\n% OBJECTIVE-20261102-END')
    edits[p] = t
    p = ms / 'docs/chap02_objective_review.tex'
    edits[p] = ('\\paragraph{来源复核与材料暴露}\n在JSON重跑之前，研究者曾授权将172题的题干、选项、标准答案和原文发送至超算Qwen3-8B进行AI辅助来源复核。'
        '模型标记15题存在疑点；对原文的后续AI辅助核查建议OBJ-116和OBJ-170由领域专家复核。'
        '该复核不是独立人工审计；8B服务事先收到答案，本次8B结果存在潜在材料暴露，不能作为未见题知识测试。\n')
    p = root / 'graduation-research/chapters/chapter02.md'; t = p.read_text(encoding='utf8')
    t = replace_once(t, r'% OBJECTIVE-20261102-BEGIN.*?% OBJECTIVE-20261102-END',
        '% OBJECTIVE-20261102-BEGIN\n## 第2章客观题JSON重跑\n\n'
        '172题、两模型各13配置、4472任务全部终态，严格解析最终JSON答案字段并以固定分母评分；'
        '结果与开放问答EAS分开。题目和来源有重叠，尚未完成独立领域专家审核；8B服务曾收到答案，存在潜在暴露。'
        '统计与逐答以客观题JSON快照和重建审计为准。\n% OBJECTIVE-20261102-END')
    edits[p] = t
    # Validate all markers before the first write.
    for p, content in edits.items():
        p.write_text(content, encoding='utf8', newline='\n')
    exp.save(full.OUT / 'results/sync_provenance.json', dict(snapshot_sha256=exp.sha(snapshot_path),
        files={str(p.relative_to(exp.WORK)).replace('\\','/'): exp.sha(p) for p in edits},
        script_sha256=exp.sha(Path(__file__))))
    print('Updated thesis and research design from audited JSON snapshot')


if __name__ == '__main__':
    main()
