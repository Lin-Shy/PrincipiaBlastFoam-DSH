"""导出真实人工盲审包并独立归档人工判断，不改变冻结模型评分。"""
import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
from pathlib import Path
import sys


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path):
    return json.loads(path.read_text())


def validate_ratings(rows, ids):
    if len(rows) != len(ids) or Counter(r['blind_id'] for r in rows) != Counter(ids):
        raise ValueError('必须逐一提交全部48个冻结盲样本，不得增删或重复')
    for row in rows:
        if row['human_verdict'] not in {'pass', 'fail', 'uncertain'}:
            raise ValueError('human_verdict必须为pass/fail/uncertain，空白不算完成')
        if not row['human_notes'].strip():
            raise ValueError('每个样本都需要真实人工理由')
    return {r['blind_id']: r for r in rows}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['export', 'analyze'])
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--ratings', type=Path)
    parser.add_argument('--scores', type=Path)
    parser.add_argument('--reviewer', help='实际人工审阅者署名，由提交方提供')
    parser.add_argument('--review-date', help='实际审阅日期，由提交方提供')
    args = parser.parse_args()
    root = args.root.resolve()
    sys.path.insert(0, str(root / 'runtime'))
    from chapter2_formal_runtime import verify
    protocol, protocol_sha = verify(root, require_snapshot=False)
    prepared = load(root / 'completion/review_prepare.json')
    sample_path = root / 'human_review/blind_sample.json'
    if digest(sample_path) != prepared['human_sample_sha256']:
        raise ValueError('冻结人工盲审包哈希变化')
    sample = load(sample_path)
    cases = sample['cases']
    ids = [c['blind_id'] for c in cases]
    if sample['protocol_sha256'] != protocol_sha or len(cases) != protocol['human_review']['sessions'] or len(set(ids)) != 48:
        raise ValueError('人工样本协议或分母漂移')
    if args.output.exists():
        raise FileExistsError('必须使用新的人工交付/分析目录')
    args.output.mkdir(parents=True)
    manifest = {'schema': 'frozen-human-review-delivery-v1', 'protocol_sha256': protocol_sha,
                'sample_sha256': digest(sample_path), 'script_sha256': digest(Path(__file__)),
                'sessions': 48, 'online_llm_calls': 0, 'handling': protocol['human_review']['handling']}
    if args.stage == 'export':
        lines = ['# 第2章真实人工盲审：48份冻结回答', '',
                 '本文件不展示方法名称或模型评分。请由真实人工审阅，不能用自动模型判断代填。', '',
                 '每份回答检查：全部必要事实是否完整正确；引用原文是否支持对应断言；模型角色、字典、条件是否错配。',
                 '所有要求均满足且引用支持填pass；有明确错误、遗漏或不支持的引用填fail；无法确定填uncertain。',
                 '在ratings.csv逐行填写human_verdict与human_notes，保留blind_id；理由需指出具体要求或引用问题。', '',
                 '同8B评分和人工判断将分别保留；48份样本不能外推为全网格人工真值。', '']
        for case in cases:
            lines.extend(['## '+case['blind_id'], '', '### 问题', '', case['question'], '', '### 回答', '', case['answer_text'], '', '### 必要要求', ''])
            for point in case['gold_points']:
                lines.append(f"- [{point['index']}] {point['requirement']}")
            for field, label in [('allowed', '允许回答'), ('forbidden', '禁止误解'), ('ambiguity', '歧义说明')]:
                lines.extend(['', '### '+label, '', '```json', json.dumps(case[field], ensure_ascii=False, indent=2), '```'])
            lines.extend(['', '### 必要权威证据', ''])
            for atom in case['gold_evidence']:
                lines.extend([f"**{atom['path']} L{atom['start']}–L{atom['end']}**（SHA-256 {atom['sha256']}）", '', '```text', atom['quote'], '```', ''])
            lines.extend(['### 回答使用的引用', ''])
            if not case['references']:
                lines.append('没有可验证的结构化引用；可能存在答案结构失败，请结合回答判断。')
            for ref in case['references']:
                lines.extend([f"**引用[{ref['index']}] {ref['path']} L{ref['start']}–L{ref['end']}**", '', '断言：'+ref['claim'], '', '```text', ref['quote'], '```', ''])
        (args.output / '人工盲审说明与证据.md').write_text('\n'.join(lines)+'\n')
        with (args.output / 'ratings.csv').open('w', newline='', encoding='utf-8-sig') as stream:
            writer = csv.DictWriter(stream, fieldnames=['blind_id', 'human_verdict', 'human_notes'])
            writer.writeheader()
            writer.writerows({'blind_id': i, 'human_verdict': '', 'human_notes': ''} for i in ids)
        manifest['files'] = {p.name: digest(p) for p in args.output.iterdir()}
    else:
        if not all([args.ratings, args.scores, args.reviewer, args.review_date]):
            raise ValueError('必须提供实际人工填写文件、冻结派生模型评分、真实审阅者署名和日期')
        with args.ratings.open(encoding='utf-8-sig', newline='') as stream:
            ratings = validate_ratings(list(csv.DictReader(stream)), ids)
        scores = load(args.scores)
        if scores['protocol_sha256'] != protocol_sha or scores['model_scored_sessions'] != 1728:
            raise ValueError('需要全量冻结派生模型评分')
        model = {r['blind_id']: r for r in scores['rows']}
        rows, counts, arms = [], Counter(), defaultdict(Counter)
        for blind in ids:
            human, scored = ratings[blind], model[blind]
            predicted = {'failure': 'fail', 'model_claimed_success': 'pass', 'unknown': 'uncertain'}[scored['strict_outcome']]
            truth = human['human_verdict']
            counts[predicted+' / '+truth] += 1
            arms[scored['arm']][truth] += 1
            rows.append({'blind_id': blind, 'human_verdict': truth, 'human_notes': human['human_notes'],
                         'model_verdict': predicted, 'identity': {k: scored[k] for k in ['arm', 'family_id', 'question_id', 'repeat']},
                         'sampled_human_correction': truth != predicted})
        comparable = sum(v for k,v in counts.items() if 'uncertain' not in k)
        positives = counts['pass / pass']+counts['pass / fail']
        negatives = counts['fail / pass']+counts['fail / fail']
        manifest.update(reviewer=args.reviewer, review_date=args.review_date, ratings_sha256=digest(args.ratings),
                        scores_sha256=digest(args.scores), provenance_limit='reviewer and date are supplied by submitter; tool does not authenticate a human identity',
                        rows=rows, confusion_counts=dict(counts), by_arm_sample_counts={k: dict(v) for k,v in arms.items()},
                        known_label_agreement=(counts['pass / pass']+counts['fail / fail'])/comparable if comparable else None,
                        comparable_known_labels=comparable,
                        falsepositive_given_model_positive=counts['pass / fail']/positives if positives else None,
                        falsenegative_given_model_negative=counts['fail / pass']/negatives if negatives else None,
                        model_unknown_samples=sum(v for k,v in counts.items() if k.startswith('uncertain /')),
                        human_uncertain_samples=sum(v for k,v in counts.items() if k.endswith('/ uncertain')),
                        limits='48 sampled human decisions only; no extrapolation to1728; original model labels preserved; unknown not counted as wrong; no LLM calls')
    (args.output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n')


if __name__ == '__main__':
    main()
