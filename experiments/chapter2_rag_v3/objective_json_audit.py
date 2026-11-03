"""Rebuild every JSON score and statistical result from frozen source records."""
import csv
from pathlib import Path
import objective_experiment as exp
import objective_json_full as full
import objective_json_strict as strict
from objective_statistics import analyze


def main():
    full.use_full()
    m = exp.verify()
    snapshot_path = full.OUT / 'results/snapshot.json'
    snap = exp.read(snapshot_path)
    rows = exp.read(full.OUT / 'scores/per_answer.json')
    qs = exp.read(exp.DATA / 'model/questions.json')
    gold = {g['id']: g for g in exp.read(exp.DATA / 'scoring/annotations.json')}
    if snap['status'] != 'closed' or snap['completed'] != m['tasks'] or len(rows) != m['tasks']:
        raise ValueError('Unclosed run')
    indexed = {(r['config_id'], r['id']): r for r in rows}
    if len(indexed) != len(rows):
        raise ValueError('Duplicate score identity')
    for c in m['configurations']:
        for q in qs:
            source = exp.read(full.OUT / 'generation' / c['config_id'] / q['id'] / 'result.json')
            if source['manifest_sha256'] != exp.sha(full.OUT / 'manifest.json'):
                raise ValueError('Result manifest mismatch')
            expected = strict.score(q, gold[q['id']], source)
            row = indexed[c['config_id'], q['id']]
            for key, value in expected.items():
                if row.get(key) != value:
                    raise ValueError(f'Score mismatch {c["config_id"]} {q["id"]} {key}')
    for c in m['configurations']:
        group = [r for r in rows if r['config_id'] == c['config_id']]
        summary = next(x for x in snap['configurations'] if x['config_id'] == c['config_id'])
        if summary['correct'] != sum(r['score'] for r in group) or summary['accuracy'] != sum(r['score'] for r in group)/len(qs):
            raise ValueError('Summary mismatch')
    if analyze(rows, m['analysis']) != snap['statistics']:
        raise ValueError('Statistics do not reconstruct')
    for name, expected_rows in [('per_answer.csv', rows), ('summary.csv', snap['configurations'])]:
        with (full.OUT / 'results' / name).open(encoding='utf-8-sig', newline='') as f:
            exported = list(csv.DictReader(f))
        if len(exported) != len(expected_rows):
            raise ValueError('Export row count mismatch: ' + name)
        for a, b in zip(exported, expected_rows):
            if any(a[k] != ('' if v is None else str(v)) for k, v in b.items()):
                raise ValueError('Export mismatch: ' + name)
    exp.save(full.OUT / 'results/json_audit.json', dict(status='passed', tasks=len(rows),
        snapshot_sha256=exp.sha(snapshot_path), manifest_sha256=exp.sha(full.OUT / 'manifest.json'),
        scoring_code_sha256=exp.sha(Path(strict.__file__)), audit_code_sha256=exp.sha(Path(__file__))))
    print('JSON audit passed:', len(rows))


if __name__ == '__main__':
    main()
