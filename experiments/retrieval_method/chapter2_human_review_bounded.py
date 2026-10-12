"""在完整分母、含缺失模型判断的派生评分上接收真实人工48盲审；零模型调用。"""
import argparse
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path
import sys

from chapter2_human_review import digest, load, validate_ratings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('root', 'ratings', 'scores', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--reviewer', required=True)
    parser.add_argument('--review-date', required=True)
    args = parser.parse_args()
    if not args.reviewer.strip() or not args.review_date.strip():
        raise ValueError('需要实际人工署名和审阅日期')
    root = args.root.resolve()
    sys.path.insert(0, str(root / 'runtime'))
    from chapter2_formal_runtime import verify
    protocol, protocol_sha = verify(root, require_snapshot=False)
    prepared = load(root / 'completion/review_prepare.json')
    sample_path = root / 'human_review/blind_sample.json'
    sample = load(sample_path)
    ids = [item['blind_id'] for item in sample['cases']]
    if (digest(sample_path) != prepared['human_sample_sha256'] or
            sample['protocol_sha256'] != protocol_sha or len(ids) != 48 or len(set(ids)) != 48):
        raise ValueError('冻结人工样本哈希、协议或分母不符')
    with args.ratings.open(encoding='utf-8-sig', newline='') as stream:
        ratings = validate_ratings(list(csv.DictReader(stream)), ids)
    scores = load(args.scores)
    identity = load(root / 'evaluation_only/identity.json')
    model = {row['blind_id']: row for row in scores['rows']}
    if (scores['protocol_sha256'] != protocol_sha or not scores.get('incomplete_grid_analysis') or
            scores['sessions_in_frozen_denominator'] != protocol['planned_sessions'] or
            len(scores['rows']) != len(identity) or set(model) != set(identity)):
        raise ValueError('需显式缺失槽位分析及全部冻结会话，不能缩减分母')
    rows, confusion, by_arm = [], Counter(), defaultdict(Counter)
    for blind in ids:
        scored, human = model[blind], ratings[blind]
        for key in ('arm', 'family_id', 'question_id', 'repeat'):
            if scored[key] != identity[blind][key]:
                raise ValueError('盲化会话身份不符')
        predicted = {'failure': 'fail', 'model_claimed_success': 'pass',
                     'unknown': 'uncertain'}[scored['strict_outcome']]
        truth = human['human_verdict']
        confusion[predicted + ' / ' + truth] += 1
        by_arm[scored['arm']][truth] += 1
        rows.append({'blind_id': blind, 'human_verdict': truth, 'human_notes': human['human_notes'],
                     'model_verdict': predicted, 'unknown_model_criteria': scored['unknown_criteria'],
                     'identity': {key: scored[key] for key in ('arm', 'family_id', 'question_id', 'repeat')},
                     'sampled_human_correction': truth != predicted})
    comparable = sum(value for key, value in confusion.items() if 'uncertain' not in key)
    positives = confusion['pass / pass'] + confusion['pass / fail']
    negatives = confusion['fail / pass'] + confusion['fail / fail']
    result = {'schema': 'real-human48-with-bounded-model-audit-v1', 'protocol_sha256': protocol_sha,
              'script_sha256': digest(Path(__file__)), 'sample_sha256': digest(sample_path),
              'scores_sha256': digest(args.scores), 'ratings_sha256': digest(args.ratings),
              'model_grid_completed': scores['full_scoring_grid_completed'],
              'model_missing_slots': len(scores['missing_slots']), 'sessions': 48,
              'reviewer': args.reviewer, 'review_date': args.review_date, 'online_llm_calls': 0,
              'rows': rows, 'confusion_counts': dict(confusion),
              'by_arm_sample_counts': {key: dict(value) for key, value in by_arm.items()},
              'comparable_known_labels': comparable,
              'known_label_agreement': (confusion['pass / pass'] + confusion['fail / fail']) / comparable if comparable else None,
              'falsepositive_given_model_positive': confusion['pass / fail'] / positives if positives else None,
              'falsenegative_given_model_negative': confusion['fail / pass'] / negatives if negatives else None,
              'model_unknown_samples': sum(value for key, value in confusion.items() if key.startswith('uncertain /')),
              'human_uncertain_samples': sum(value for key, value in confusion.items() if key.endswith('/ uncertain')),
              'handling': protocol['human_review']['handling'],
              'limits': '实际人工48样本与模型缺失/未知分开；保留原模型标签，仅样本纠正，不外推1728会话。署名/日期由提交方提供，工具不认证身份。'}
    if args.output.exists():
        raise FileExistsError('必须使用新的真实人工分析目录')
    args.output.mkdir(parents=True)
    (args.output / 'manifest.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
