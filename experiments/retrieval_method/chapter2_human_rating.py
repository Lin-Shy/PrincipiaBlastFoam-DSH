"""离线五分制真人评分：生成独立HTML、验证封存结果、派生小样本统计。零模型调用。"""
import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime
import hashlib
import json
from pathlib import Path

SCHEMA = 'chapter2-human-rating-v1'
FIELDS = ('blind_id', 'question', 'answer_text', 'references', 'gold_evidence',
          'allowed', 'forbidden', 'ambiguity', 'gold_points')
LABELS = {'full': '完整方法', 'no_cross': '删除跨来源边', 'no_graph': '无图 BM25',
          'e5': 'E5', 'graphify_native': 'Graphify 原生', 'graphify_text_adapter': 'Graphify 文本适配'}
PAYLOAD_FIELDS = ('schema', 'binding', 'reviewer', 'rows', 'created_at', 'finalized_at',
                  'revision_phase', 'parent_seal_sha256')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def seal_digest(document):
    return hashlib.sha256(canonical({k: document[k] for k in PAYLOAD_FIELDS}).encode()).hexdigest()


def write(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        stream.write(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def frozen_inputs(experiment, scores_path):
    """只校验本工具所需冻结输入，不要求重建历史在线运行环境。"""
    root = Path(experiment) / 'formal/frozen_001'
    protocol_sha = digest(root / 'protocol.json')
    if read(root / 'seal.json')['protocol_sha256'] != protocol_sha:
        raise ValueError('冻结协议哈希不符')
    protocol = read(root / 'protocol.json')
    sample_path = root / 'human_review/blind_sample.json'
    sample = read(sample_path)
    prepared = read(root / 'completion/review_prepare.json')
    sample_sha = digest(sample_path)
    if prepared['human_sample_sha256'] != sample_sha or sample['protocol_sha256'] != protocol_sha:
        raise ValueError('冻结盲样本哈希或协议不符')
    cases = [{k: c[k] for k in FIELDS} for c in sample['cases']]
    ids = [c['blind_id'] for c in cases]
    if len(ids) != 48 or len(set(ids)) != 48 or protocol['human_review']['sessions'] != 48:
        raise ValueError('必须保留全部48份唯一冻结盲样本')
    identity_path = root / 'evaluation_only/identity.json'
    identity = read(identity_path)
    scores = read(scores_path)
    score_rows = scores['rows']
    model = {r['blind_id']: r for r in score_rows}
    if (scores['protocol_sha256'] != protocol_sha or not scores.get('incomplete_grid_analysis')
            or scores['sessions_in_frozen_denominator'] != protocol['planned_sessions']
            or len(score_rows) != len(identity) or len(model) != len(score_rows)
            or set(model) != set(identity) or len(identity) != protocol['planned_sessions']):
        raise ValueError('派生模型评分必须保留完整冻结分母及未知槽位')
    for blind, row in model.items():
        for k in ('arm', 'family_id', 'question_id', 'repeat', 'answer_sha256'):
            if row[k] != identity[blind][k]:
                raise ValueError('模型评分身份不符: ' + blind)
        if row['strict_outcome'] not in ('failure', 'model_claimed_success', 'unknown'):
            raise ValueError('模型判断非法')
    binding = {'protocol_sha256': protocol_sha, 'sample_sha256': sample_sha,
               'scores_sha256': digest(scores_path), 'sessions': 48}
    unblind = {'schema': 'chapter2-human-rating-unblind-v1', 'binding': binding,
               'labels': LABELS, 'rows': [{'blind_id': blind, 'identity': identity[blind],
                 'model': {k: model[blind][k] for k in ('strict_outcome', 'strict_bounds',
                    'citation_accuracy_bounds', 'citation_state', 'unknown_criteria')}} for blind in ids]}
    return cases, binding, unblind, {'protocol.json': protocol_sha, 'blind_sample.json': sample_sha,
                                    'identity.json': digest(identity_path), 'scores.json': digest(scores_path)}


def build(experiment, scores, output):
    cases, binding, unblind, hashes = frozen_inputs(experiment, scores)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    write(output / 'unblind.json', unblind)
    data = {'schema': SCHEMA, 'binding': binding, 'cases': cases,
            'unblind_sha256': digest(output / 'unblind.json')}
    template = Path(__file__).with_name('human_rating.html').read_text(encoding='utf-8')
    javascript = Path(__file__).with_name('human_rating.js').read_text(encoding='utf-8')
    embedded = json.dumps(data, ensure_ascii=False).replace('<', '\\u003c').replace('\u2028', '\\u2028').replace('\u2029', '\\u2029')
    html = template.replace('__REVIEW_SCRIPT__', javascript).replace('__REVIEW_DATA__', embedded)
    (output / '人工评分.html').write_text(html, encoding='utf-8')
    (output / '使用说明.md').write_text(DELIVERY_GUIDE, encoding='utf-8')
    manifest = {'schema': 'chapter2-human-rating-delivery-v1', 'sessions': 48,
                'human_completed': 0, 'model_calls': 0, 'inputs_sha256': hashes,
                'sources_sha256': {p.name: digest(p) for p in (Path(__file__),
                    Path(__file__).with_name('human_rating.html'), Path(__file__).with_name('human_rating.js'))},
                'files_sha256': {p.name: digest(p) for p in output.iterdir()},
                'limits': '五分制新增人工量表，备注选填；不映射二元真值，不修改原冻结评分。'}
    write(output / 'manifest.json', manifest)
    return manifest


def is_score(value):
    return value == 'uncertain' or (type(value) is int and 1 <= value <= 5)


def timestamp(value):
    if not isinstance(value, str):
        raise ValueError('时间字段必须为ISO格式')
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('时间字段必须含时区')
    return parsed


def validate(document, binding, ids, require_sealed=True):
    if document.get('schema') != SCHEMA or document.get('binding') != binding:
        raise ValueError('结果版本或冻结输入哈希不符')
    if document.get('status') not in ('draft', 'sealed'):
        raise ValueError('结果状态非法')
    if require_sealed and document['status'] != 'sealed':
        raise ValueError('分析只接收全部完成的封存JSON')
    reviewer = document['reviewer']
    if not isinstance(reviewer.get('id'), str) or not reviewer['id'].strip():
        raise ValueError('需要审阅者代号')
    for key in ('participated_in_development', 'previously_exposed'):
        value = reviewer.get(key)
        if type(value) is not bool and not (document['status'] == 'draft' and value is None):
            raise ValueError('需要明确记录审阅者背景')
    rows = document['rows']
    if len(rows) != len(ids) or Counter(r['blind_id'] for r in rows) != Counter(ids):
        raise ValueError('必须保留48份样本，不得增删、重复编号')
    created = timestamp(document['created_at'])
    for row in rows:
        for k in ('claim_correctness', 'citation_support'):
            if not is_score(row[k]) and not (document['status'] == 'draft' and row[k] is None):
                raise ValueError('分数只能为1–5整数或uncertain；空值仅允许草稿')
        if not isinstance(row['notes'], str):
            raise ValueError('备注必须为文本，可留空')
        if row['updated_at'] is not None:
            timestamp(row['updated_at'])
        elif any(row[k] is not None for k in ('claim_correctness', 'citation_support')):
            raise ValueError('已评分记录缺少时间')
    if document['revision_phase'] not in ('blind', 'post_unblind'):
        raise ValueError('修订阶段非法')
    parent = document['parent_seal_sha256']
    if document['revision_phase'] == 'blind' and parent is not None:
        raise ValueError('盲审原版不能带修订父版本')
    if document['revision_phase'] == 'post_unblind' and (not isinstance(parent, str)
            or len(parent) != 64 or any(c not in '0123456789abcdef' for c in parent)):
        raise ValueError('解盲后修订必须绑定原封存版本')
    if document['status'] == 'sealed':
        finalized = timestamp(document['finalized_at'])
        if finalized < created or any(timestamp(r['updated_at']) > finalized for r in rows):
            raise ValueError('封存时间先于评分时间')
        if document.get('sealed_payload_sha256') != seal_digest(document):
            raise ValueError('封存内容校验失败')
    elif document['finalized_at'] is not None or document.get('sealed_payload_sha256') is not None:
        raise ValueError('草稿不能声称已经封存')
    return {r['blind_id']: r for r in rows}


def distribution(rows, field):
    values = [r[field] for r in rows]
    numeric = [v for v in values if type(v) is int]
    return {'counts': {str(k): values.count(k) for k in range(1, 6)},
            'valid_scores': len(numeric), 'uncertain': values.count('uncertain'),
            'mean': sum(numeric) / len(numeric) if numeric else None}


def analyze(experiment, scores, ratings, output):
    cases, binding, unblind, hashes = frozen_inputs(experiment, scores)
    document = read(ratings)
    rows = validate(document, binding, [c['blind_id'] for c in cases])
    grouped = defaultdict(list)
    comparisons = []
    for row in unblind['rows']:
        human = rows[row['blind_id']]
        grouped[row['identity']['arm']].append(human)
        comparisons.append({**row, 'human': human})
    dimensions = ('claim_correctness', 'citation_support')
    summary = {'schema': 'chapter2-human-rating-analysis-v1', 'binding': binding,
               'ratings_sha256': digest(ratings), 'inputs_sha256': hashes,
               'script_sha256': digest(__file__), 'reviewer': document['reviewer'],
               'revision_phase': document['revision_phase'], 'parent_seal_sha256': document['parent_seal_sha256'],
               'sealed_payload_sha256': document['sealed_payload_sha256'], 'sessions': 48,
               'families': len({r['identity']['family_id'] for r in unblind['rows']}), 'model_calls': 0,
               'overall': {k: distribution(list(rows.values()), k) for k in dimensions},
               'by_arm': {arm: {k: distribution(items, k) for k in dimensions} for arm, items in grouped.items()},
               'rows': comparisons,
               'limits': '仅48采样会话描述统计，同族相关；五分制不转换pass/fail，不计算二元一致率，不外推1728会话。背景由审阅者自报，不认证身份。'}
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    write(output / '人工评分.json', document)
    write(output / 'analysis.json', summary)
    with (output / 'comparison.csv').open('x', encoding='utf-8-sig', newline='') as stream:
        fields = ['blind_id', 'arm', 'family_id', 'question_id', 'repeat', *dimensions,
                  'notes', 'model_strict_outcome', 'model_citation_state']
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for r in comparisons:
            record = {k: r['identity'][k] for k in ('arm', 'family_id', 'question_id', 'repeat')}
            record.update({k: r['human'][k] for k in ('blind_id', *dimensions, 'notes')})
            record.update(model_strict_outcome=r['model']['strict_outcome'], model_citation_state=r['model']['citation_state'])
            # 防止备注或代号被表格软件解释成公式，JSON保留原始文本。
            writer.writerow({k: csv_safe(v) for k, v in record.items()})
    lines = ['# 第2章48样本人工五分制评分', '',
             f"审阅者：{document['reviewer']['id']}；修订阶段：{document['revision_phase']}。", '',
             '| 方法 | 事实均分（有效/无法判断） | 引用均分（有效/无法判断） |',
             '|---|---|---|']
    for arm, stats in summary['by_arm'].items():
        cells = []
        for k in dimensions:
            d = stats[k]
            mean = f"{d['mean']:.2f}" if d['mean'] is not None else '—'
            cells.append(f"{mean}（{d['valid_scores']}/{d['uncertain']}）")
        lines.append(f"| {LABELS[arm]} | {' | '.join(cells)} |")
    lines.extend(['', summary['limits'], '', '原模型未知项保持未知；人工分数与原模型判断分别保留。'])
    (output / 'report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    write(output / 'manifest.json', {'schema': 'chapter2-human-rating-analysis-manifest-v1',
          'inputs_sha256': {**hashes, 'ratings.json': digest(ratings)}, 'model_calls': 0,
          'files_sha256': {p.name: digest(p) for p in output.iterdir()}})
    return summary


def csv_safe(value):
    return "'" + value if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@')) else value


DELIVERY_GUIDE = '''# 第2章人工五分制评分

1. 双击 `人工评分.html`，使用近期版本的Chrome、Edge或Firefox，无需服务、网络或模型调用。
2. 填一次审阅者代号及两项背景信息。对每份回答点击事实、引用两项1–5分；无法确认请选择“无法判断”。备注选填。
3. 页面自动缓存进度；请定期下载“草稿JSON”，换设备、移动页面或缓存失效后用“导入评分”继续。缓存不是正式归档。
4. 完成48份后点击“封存并下载JSON”，确认浏览器已保存文件；可同时下载CSV供表格查看。JSON是复核、续审和统计的权威格式。
5. 封存下载后点击“加载解盲文件”，选择本目录 `unblind.json`，查看各方法回答及模型判断。不要在盲审完成前自行查看该文件。
6. 封存版本只读；解盲后如需修改，点击“建立解盲后修订”，单独下载新版本，保留原文件。

事实1–5分依次为：主要错误或未回答、明显错误或遗漏、部分正确但有重要缺口、基本完整正确有轻微问题、全部必要事实完整正确。
引用1–5分依次为：无有效支持、多数重要断言未获支持、部分支持但有重要缺口、主要断言获支持有轻微问题、全部需引用断言获支持。
分数不换算二元通过/失败，无法判断不计为低分。无有效引用的答案可按引用1分评价。

模型判断与人工分数不是同一量表。页面保留原文、LaTeX公式源码及原文行号，不联网渲染或改写回答。
人工意见只描述48份采样会话，不替换原1728会话评分；同事实族样本有关联，不作独立样本推断。审阅者背景为自报信息。
理由选填是本轮五分制协议的新约定，区别于旧盲审CSV强制理由的协议。当前交付没有人工评分，不能把测试数据当作真人结果。

维护及生成、分析命令见源码项目 `experiments/retrieval_method/human_rating_README.md`。
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=('build', 'analyze'))
    parser.add_argument('--experiment', type=Path, required=True)
    parser.add_argument('--scores', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--ratings', type=Path)
    args = parser.parse_args()
    if args.stage == 'build':
        result = build(args.experiment, args.scores, args.output)
    else:
        if not args.ratings:
            parser.error('analyze需要--ratings封存JSON')
        result = analyze(args.experiment, args.scores, args.ratings, args.output)
    print(json.dumps({k: result[k] for k in ('schema', 'sessions', 'model_calls')}, ensure_ascii=False))


if __name__ == '__main__':
    main()
