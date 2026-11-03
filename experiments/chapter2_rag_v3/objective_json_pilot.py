"""Matched pilot of direct extraction from the existing final-action JSON.

The original experiment and its manifest remain untouched.  No gold is read by
generation: pilot files are selected using question text/type only.
"""
import argparse
import hashlib
import json
from pathlib import Path

import objective_experiment as base
import objective_scoring as rules

ROOT = base.BASE / 'objective_json_v1'
PILOT = ROOT / 'pilot'
ORIGINAL = base.OUT
SOURCE_DATA = base.DATA
FORMAT = ('\n本题为客观题。遵守已有工具和final JSON协议。最终JSON的answer字段'
          '只填写唯一答案，不包含解释、标记、换行或多个候选；解释不要放入answer。'
          '单选只填A/B/C/D；判断只填正确或错误；填空及短答只填原始键名、'
          '配置值或数值。数值使用题目指定单位，不加单位后缀。')


def question_text(q):
    options = '\n' + '\n'.join(k + '. ' + v for k, v in q['options'].items()) if q.get('options') else ''
    return q['question'] + options + FORMAT


def score(q, gold, result):
    """The agent already parsed the strict final action; score its answer field."""
    answer = result.get('answer') if result else None
    if result and result.get('status') == 'answered':
        turns = result.get('turns') or []
        action = turns[-1].get('action', {}) if turns else {}
        if (not isinstance(answer, str) or action.get('action') != 'final'
                or action.get('answer') != answer or '\n' in answer or '\r' in answer):
            return dict(id=q['id'], type=q['type'], raw_answer=answer or '', normalized_answer='',
                        score=0, format_valid=False, reason='invalid_json_answer', scoring_version='json_answer_v1')
        result = dict(result, answer='FINAL: ' + answer)
    row = rules.score(q, gold, result or {})
    row['raw_answer'] = answer or ''
    row['scoring_version'] = 'json_answer_v1'
    return row


def prepare():
    if (PILOT / 'manifest.json').exists():
        return
    questions = base.read(SOURCE_DATA / 'model/questions.json')
    # Evenly spaced by frozen ID within each type; selection does not use scores or answers.
    chosen = []
    for kind in ('fill', 'short', 'single', 'judge'):
        group = sorted((q for q in questions if q['type'] == kind), key=lambda q: q['id'])
        chosen.extend(group[(i * (len(group)-1)) // 4] for i in range(5))
    ids = {q['id'] for q in chosen}
    annotations = [g for g in base.read(SOURCE_DATA / 'scoring/annotations.json') if g['id'] in ids]
    base.save(PILOT / 'data/model/questions.json', chosen)
    base.save(PILOT / 'data/scoring/annotations.json', annotations)
    old = base.read(ORIGINAL / 'manifest.json')
    configs = [c for c in old['configurations'] if c['method_id'] in ('graph', 'bm25', 'direct')]
    if len(configs) != 6:
        raise ValueError('Expected two models and three methods: ' + repr([c['method_id'] for c in configs]))
    bindings = dict(old['bindings'])
    for p in (Path(__file__), PILOT / 'data/model/questions.json', PILOT / 'data/scoring/annotations.json'):
        bindings[str(p.relative_to(base.WORK)).replace('\\', '/')] = base.sha(p)
    old.update(schema='objective_json_pilot_v1', created=base.now(), questions=len(chosen),
               tasks=len(chosen)*len(configs), configurations=configs, bindings=bindings,
               question_file=str((PILOT / 'data/model/questions.json').relative_to(base.WORK)),
               format_instruction=FORMAT, scoring='json_answer_v1; identical type/alias rules as objective_rules_v1',
               pilot_decision='Both models: >=80% valid among answered; pooled fixed-denominator valid rate >=15 percentage points above matched original; neither model falls >5 points. Descriptive only; exposure and deployment caveats apply.')
    base.save(PILOT / 'manifest.json', old)


def use_pilot():
    base.OUT = PILOT
    base.MANIFEST = PILOT / 'manifest.json'
    base.DATA = PILOT / 'data'
    base.question_text = question_text
    # Original score-side data must also be blocked, in addition to the pilot copy.
    guard = base.generation_guard
    def guarded():
        import os, sys
        banned = str(SOURCE_DATA / 'scoring').lower()
        def hook(name, args):
            if name == 'open' and args and isinstance(args[0], (str, bytes, os.PathLike)):
                if os.path.abspath(os.fsdecode(args[0])).lower().startswith(banned):
                    raise PermissionError('Original scoring data forbidden during generation')
        sys.addaudithook(hook)
        guard()
    base.generation_guard = guarded


def report():
    manifest = base.read(PILOT / 'manifest.json')
    qs = base.read(PILOT / 'data/model/questions.json')
    gold = {g['id']: g for g in base.read(PILOT / 'data/scoring/annotations.json')}
    rows = []
    for c in manifest['configurations']:
        for q in qs:
            path = PILOT / 'generation' / c['config_id'] / q['id'] / 'result.json'
            previous = ORIGINAL / 'generation' / c['config_id'] / q['id'] / 'result.json'
            if not path.exists():
                continue
            new = base.read(path)
            old = base.read(previous)
            a, b = score(q, gold[q['id']], new), rules.score(q, gold[q['id']], old)
            rows.append(dict(config=c['config_id'], model=c['model_key'], method=c['method_id'], id=q['id'],
                             type=q['type'], new_status=new['status'], old_status=old['status'],
                             new_valid=a['format_valid'], old_valid=b['format_valid'],
                             new_score=a['score'], old_score=b['score'], new_reason=a['reason']))
    summary = {}
    for model in ('qwen3_8b', 'qwen3_14b'):
        group = [r for r in rows if r['model'] == model]
        answered = sum(r['new_status'] == 'answered' for r in group)
        n = len(group)
        summary[model] = dict(n=n, answered=answered, new_valid=sum(r['new_valid'] for r in group),
                              old_valid=sum(r['old_valid'] for r in group),
                              valid_among_answered=sum(r['new_valid'] for r in group)/answered if answered else 0,
                              new_fixed_valid_rate=sum(r['new_valid'] for r in group)/n if n else 0,
                              old_fixed_valid_rate=sum(r['old_valid'] for r in group)/n if n else 0,
                              new_correct=sum(r['new_score'] for r in group), old_correct=sum(r['old_score'] for r in group))
    complete = len(rows) == manifest['tasks']
    improvement = (sum(r['new_valid'] for r in rows)-sum(r['old_valid'] for r in rows))/len(rows) if rows else 0
    passed = complete and improvement >= .15 and all(
        s['valid_among_answered'] >= .8 and s['new_fixed_valid_rate'] >= s['old_fixed_valid_rate']-.05
        for s in summary.values())
    result = dict(manifest_sha256=base.sha(PILOT / 'manifest.json'), complete=complete,
                  rows=len(rows), planned=manifest['tasks'], pooled_valid_improvement=improvement,
                  decision='pass' if passed else ('fail' if complete else 'pending'), models=summary,
                  caveat='Same questions as historical experiment; 8B service saw gold during later review; not a blinded knowledge test.')
    base.save(PILOT / 'report.json', result)
    base.save(PILOT / 'per_answer.json', rows)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=('prepare', 'check', 'run', 'report'))
    parser.add_argument('--model', choices=('qwen3_8b', 'qwen3_14b'))
    parser.add_argument('--workers', type=int)
    args = parser.parse_args()
    if args.command == 'prepare':
        prepare()
    elif args.command == 'report':
        report()
    else:
        use_pilot()
        if args.command == 'check':
            base.check()
        else:
            base.run(args.model, workers=args.workers)
