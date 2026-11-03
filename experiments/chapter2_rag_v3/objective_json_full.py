"""Full JSON-answer rerun, gated on a closed passing matched pilot."""
import argparse
from pathlib import Path
import objective_experiment as base
import objective_json_pilot as pilot

OUT = base.BASE / 'objective_json_v2' / 'full'
ORIGINAL = base.BASE / 'objective200'
DATA = base.DATA
pilot.PILOT = base.BASE / 'objective_json_v3' / 'pilot'


def prepare():
    pilot_result = base.read(pilot.PILOT / 'report.json')
    if (pilot_result.get('decision') != 'pass'
            or pilot_result.get('scoring_version') != 'json_answer_strict_v2'
            or pilot_result.get('manifest_sha256') != base.sha(pilot.PILOT / 'manifest.json')):
        raise ValueError('Closed and passing bound pilot using strict JSON scoring required')
    if (OUT / 'manifest.json').exists():
        return
    m = base.read(ORIGINAL / 'manifest.json')
    bindings = dict(m['bindings'])
    import objective_json_strict
    for p in (Path(__file__), Path(pilot.__file__), Path(objective_json_strict.__file__), pilot.PILOT / 'manifest.json', pilot.PILOT / 'report.json'):
        bindings[str(p.relative_to(base.WORK)).replace('\\', '/')] = base.sha(p)
    m.update(schema='objective_json_full_v1', created=base.now(), bindings=bindings,
             format_instruction=pilot.FORMAT, scoring='json_answer_strict_v2; fixed denominator',
             pilot_manifest_sha256=base.sha(pilot.PILOT / 'manifest.json'),
             pilot_report_sha256=base.sha(pilot.PILOT / 'report.json'),
             limitation='Repeat on previously used items; 8B service received answer keys in prior source review; not unseen knowledge evaluation.')
    base.save(OUT / 'manifest.json', m)


def use_full():
    base.OUT = OUT
    base.MANIFEST = OUT / 'manifest.json'
    base.DATA = DATA
    base.FORMAT = pilot.FORMAT
    base.question_text = pilot.question_text


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=('prepare', 'check', 'run', 'report'))
    parser.add_argument('--model', choices=('qwen3_8b', 'qwen3_14b'))
    parser.add_argument('--workers', type=int)
    args = parser.parse_args()
    if args.command == 'prepare':
        prepare()
    else:
        use_full()
        if args.command == 'check':
            base.check()
        elif args.command == 'run':
            base.run(args.model, workers=args.workers)
        else:
            import objective_scoring, objective_json_strict
            objective_scoring.score = objective_json_strict.score
            base.report()
