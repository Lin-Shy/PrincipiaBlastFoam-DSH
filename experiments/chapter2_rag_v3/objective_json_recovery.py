"""Resume the JSON pilot in a distinct batch after a recorded connectivity outage."""
import argparse
import shutil
from pathlib import Path
import objective_experiment as base
import objective_json_pilot as pilot
import objective_json_strict as strict

PREVIOUS = pilot.PILOT
CURRENT = base.BASE / 'objective_json_v3' / 'pilot'
pilot.PILOT = CURRENT


def prepare():
    if (CURRENT / 'manifest.json').exists():
        raise ValueError('Recovery manifest already exists; do not rewrite a frozen batch')
    pilot.prepare()
    manifest = CURRENT / 'manifest.json'
    m = base.read(manifest)
    # Bind this wrapper and strict scorer before issuing the new requests.
    for p in (Path(__file__), Path(strict.__file__), PREVIOUS / 'manifest.json'):
        m['bindings'][str(p.relative_to(base.WORK)).replace('\\', '/')] = base.sha(p)
    m.update(schema='objective_json_recovery_pilot_v1', scoring='json_answer_strict_v2',
             recovery='Reuse v2 8B results byte-for-byte; new 14B pilot identities after all v2 requests timed out without receipts and service restart. Remote acceptance of old requests remains unknown.')
    base.save(manifest, m)
    items = []
    for p in (PREVIOUS / 'generation').rglob('result.json'):
        if not p.parent.parent.name.startswith('qwen3_8b__'):
            continue
        target = CURRENT / p.relative_to(PREVIOUS)
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.copy2(p, target)
        if base.sha(p) != base.sha(target):
            raise ValueError('Reused result hash differs')
        items.append(dict(path=str(p.relative_to(base.WORK)).replace('\\', '/'), sha256=base.sha(p)))
    if len(items) != 60:
        raise ValueError(f'Expected 60 prior 8B results, got {len(items)}')
    base.save(CURRENT / 'reused_8b.json', items)


def report():
    pilot.score = strict.score
    pilot.report()
    path = CURRENT / 'report.json'
    result = base.read(path)
    result['scoring_version'] = 'json_answer_strict_v2'
    result['reused_8b_inventory_sha256'] = base.sha(CURRENT / 'reused_8b.json')
    base.save(path, result)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=('prepare', 'check', 'run', 'report'))
    parser.add_argument('--workers', type=int)
    args = parser.parse_args()
    if args.command == 'prepare':
        prepare()
    elif args.command == 'report':
        report()
    else:
        pilot.use_pilot()
        if args.command == 'check':
            base.check()
        else:
            base.run('qwen3_14b', workers=args.workers)
