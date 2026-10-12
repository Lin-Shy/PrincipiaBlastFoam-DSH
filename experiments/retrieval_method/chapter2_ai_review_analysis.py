"""封存48盲样本AI判断后解盲对照；不称真人、真值或修改原Qwen标签。"""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import sys


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path):
    return json.loads(path.read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('root', 'reviews', 'scores', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    sys.path.insert(0, str(root / 'runtime'))
    from chapter2_formal_runtime import verify
    protocol, protocol_sha = verify(root, require_snapshot=False)
    collection = load(args.reviews / 'manifest.json')
    sample_file = root / 'human_review/blind_sample.json'
    sample = load(sample_file)
    sample_ids = {case['blind_id'] for case in sample['cases']}
    amendment = root / 'execution_amendments/ai_review_001'
    config_sha = sha(amendment / 'execution_config.json')
    if (load(amendment / 'seal.json')['execution_config_sha256'] != config_sha or
            collection['verification_amendment_sha256'] != config_sha or
            collection['blind_sample_sha256'] != sha(sample_file) or
            collection['protocol_sha256'] != protocol_sha or collection['sessions'] != 48 or
            collection['actual_human_review'] is not False or collection['reviewer_type'] != 'AI'):
        raise ValueError('AI复核修订/原样本身份或非真人标识不一致')
    for relative, expected in collection['files_sha256'].items():
        if sha(args.reviews / relative) != expected:
            raise ValueError('已封存AI判断发生变化')
    records = {path.stem: load(path) for path in (args.reviews / 'reviews').glob('*.json')}
    if len(records) != 48 or set(records) != sample_ids:
        raise ValueError('必须保留全部冻结48样本')
    scores = load(args.scores)
    identity = load(root / 'evaluation_only/identity.json')
    model = {row['blind_id']: row for row in scores['rows']}
    if (scores['protocol_sha256'] != protocol_sha or len(scores['rows']) != 1728 or
            set(model) != set(identity)):
        raise ValueError('模型派生评分需要全部1728冻结会话与原身份')
    rows, confusion, by_arm = [], Counter(), defaultdict(Counter)
    for blind in sorted(sample_ids):
        review, scored = records[blind], model[blind]
        if (review['ai_verdict'] not in {'pass', 'fail', 'uncertain'} or not review['ai_notes'].strip() or
                review['actual_human_review'] is not False or review['method_labels_presented'] is not False or
                review['qwen_judgement_presented_for_sample'] is not False):
            raise ValueError('复核来源/理由/盲化标识不符')
        case = next(case for case in sample['cases'] if case['blind_id'] == blind)
        case_sha = hashlib.sha256(json.dumps(case, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        if review['case_sha256'] != case_sha:
            raise ValueError('AI判断未绑定原冻结样本')
        for key in ('arm', 'family_id', 'question_id', 'repeat'):
            if scored[key] != identity[blind][key]:
                raise ValueError('样本解盲身份不符')
        predicted = {'failure': 'fail', 'model_claimed_success': 'pass', 'unknown': 'uncertain'}[scored['strict_outcome']]
        judgement = review['ai_verdict']
        confusion[predicted + ' / ' + judgement] += 1
        by_arm[scored['arm']][judgement] += 1
        rows.append({'blind_id': blind, 'ai_verdict': judgement, 'ai_notes': review['ai_notes'],
                     'model_verdict': predicted, 'unknown_model_criteria': scored['unknown_criteria'],
                     'identity': {key: scored[key] for key in ('arm', 'family_id', 'question_id', 'repeat')},
                     'labels_disagree': judgement != predicted})
    known = sum(value for key, value in confusion.items() if 'uncertain' not in key)
    result = {'schema': 'frozen48-independent-ai-comparison-v1', 'protocol_sha256': protocol_sha,
              'script_sha256': sha(Path(__file__)), 'scores_sha256': sha(args.scores),
              'review_collection_sha256': sha(args.reviews / 'manifest.json'),
              'sample_sha256': sha(sample_file), 'verification_amendment_sha256': config_sha,
              'sessions': 48, 'independent_families': 8, 'reviewer_type': 'AI',
              'reviewer': 'Codex primary assistant (AI)', 'review_date': '2026-10-04',
              'actual_human_review': False, 'model_grid_completed': scores.get('full_scoring_grid_completed', True),
              'model_missing_slots': len(scores.get('missing_slots', [])), 'rows': rows,
              'confusion_counts': dict(confusion), 'by_arm_sample_counts': {key: dict(value) for key, value in by_arm.items()},
              'comparable_known_labels': known,
              'known_label_agreement': (confusion['pass / pass'] + confusion['fail / fail']) / known if known else None,
              'model_unknown_samples': sum(value for key, value in confusion.items() if key.startswith('uncertain /')),
              'ai_uncertain_samples': sum(value for key, value in confusion.items() if key.endswith('/ uncertain')),
              'new_external_model_api_calls': 0,
              'limits': '用户将真人输入环节委托AI后的补充审计；没有真人真值。两个AI不一致不能直接认定原Qwen评分错误。不外推48到1728，不覆盖原标签，不补作原缺失判断。'}
    if args.output.exists():
        raise FileExistsError('需新的AI对照分析目录')
    args.output.mkdir(parents=True)
    (args.output / 'manifest.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')


if __name__ == '__main__':
    main()
