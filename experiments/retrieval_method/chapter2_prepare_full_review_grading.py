"""另存全量复核后评分执行包；原余额恢复包和固定测量文件不覆盖。"""
import argparse
import ast
import hashlib
import json
from pathlib import Path

FULL_MODE = 'all_preselected_only_after_complete_global_source_review'


def read(path):
    return json.loads(Path(path).read_text('utf-8'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def transform(original, replacements):
    extended = original
    for before, after in replacements:
        if extended.count(before) != 1:
            raise ValueError('full release requires an exact single frozen control-flow site')
        extended = extended.replace(before, after)
    restored = extended
    for before, after in reversed(replacements):
        restored = restored.replace(after, before)
    if ast.dump(ast.parse(restored)) != ast.dump(ast.parse(original)):
        raise ValueError('unexpected full-review execution change')
    return extended


def prepare(base_package, citation_policy, output):
    base_package, citation_policy, output = [Path(p).resolve() for p in (base_package, citation_policy, output)]
    if output.exists():
        raise FileExistsError('new immutable full-review execution package required')
    base = read(base_package / 'manifest.json')
    if base['grading_mode'] != 'non_preselected_only':
        raise ValueError('registered unselected-only billing package required as base')
    for relative, digest in base['files_sha256'].items():
        if sha(base_package / relative) != digest:
            raise ValueError('base execution byte drift')
    for role in base['bases'].values():
        if sha(role['registration_file']) != role['registration_sha256']:
            raise ValueError('base registration drift')
        for relative, digest in role['runtime_source_sha256'].items():
            if sha(Path(role['runtime']) / relative) != digest:
                raise ValueError('base frozen runtime drift')
    policy = read(citation_policy)
    if policy['plan_sha256'] != base['bases']['generation']['registration_sha256']:
        raise ValueError('citation policy belongs to another generation plan')
    files = {name: (base_package / name).read_bytes() for name in base['files_sha256']}
    worker_changes = [
        ("if any(a.split('=')[0] in {'--review-pack','--review-verdicts'} for a in _BillingSys.argv[1:]):\n    raise ValueError('billing execution package only grades non-preselected answers')\n", "from full_review import load_complete_independent_review\n"),
        ("parser.add_argument('--review-pack', type=Path); parser.add_argument('--review-verdicts', type=Path)",
         "parser.add_argument('--review-pack', type=Path); parser.add_argument('--review-verdicts', type=Path)\n    for name in ('citation-policy','citation-pack','citation-verdicts'):\n        parser.add_argument('--' + name, type=Path, required=True)"),
        ("load_independent_review(args.review_pack, args.review_verdicts, selection, setup, with_rows=True)",
         "load_complete_independent_review(args, selection, setup, load_independent_review)")]
    guard_changes = [("if manifest['grading_mode'] != 'non_preselected_only':",
                      f"if manifest['grading_mode'] != {FULL_MODE!r}:")]
    controller_changes = [
        ("choices=['generation', 'grading']", "choices=['grading']"),
        ("parser.add_argument('--inspect-only', action='store_true')",
         "parser.add_argument('--inspect-only', action='store_true')\n    for name in ('review-pack','review-verdicts','citation-policy','citation-pack','citation-verdicts'):\n        parser.add_argument('--' + name, type=Path, required=True)"),
        ("'--review-selection', str(args.review_selection)]",
         "'--review-selection', str(args.review_selection),\n            '--review-pack', str(args.review_pack), '--review-verdicts', str(args.review_verdicts),\n            '--citation-policy', str(args.citation_policy), '--citation-pack', str(args.citation_pack),\n            '--citation-verdicts', str(args.citation_verdicts)]"),
        ("    for cell_id, qid in selected:\n        if (args.score_output / cell_id / 'sessions' / qid / 'score.json').exists():\n            raise ValueError('preselected scores already exist; this recovery package is unselected-only')",
         "    from full_review import verify_complete_release\n    from types import SimpleNamespace\n    release_args = SimpleNamespace(**{**vars(args), 'output': args.score_output})\n    _, _, _, full_release = verify_complete_release(release_args, selection, read(args.evaluation), persist=not args.inspect_only)\n    selected = set()  # Completion now includes every registered selected task."),
        ("'planned_cells': len(plan['cells']), 'preselected_scores_enabled': False,",
         "'planned_cells': len(plan['cells']), 'preselected_scores_enabled': True,\n        'global_full_review_release': full_release,"),
        ("'plan_sha256': sha(args.plan), 'preselected_scores_enabled': False,",
         "'plan_sha256': sha(args.plan), 'preselected_scores_enabled': True,")]
    changes = {'grading.py': worker_changes, 'guard.py': guard_changes, 'controller.py': controller_changes}
    for name, replacements in changes.items():
        files[name] = transform(files[name].decode('utf-8'), replacements).encode('utf-8')
    app = Path(__file__).resolve().parent
    files['full_review.py'] = (app / 'chapter2_full_review_release.py').read_bytes()
    files['full_snapshot.py'] = (app / 'chapter2_full_review_snapshot_binding.py').read_bytes()
    for name in ['chapter2_citation_original_review.py', 'chapter2_citation_support.py']:
        relative = 'experiments/retrieval_method/' + name
        source = citation_policy.parent / 'runtime' / relative
        if sha(source) != policy['runtime_source_sha256'][relative]:
            raise ValueError('citation validator frozen source drift')
        files[name] = source.read_bytes()
    manifest = {**base, 'grading_mode': FULL_MODE,
        'files_sha256': {name: hashlib.sha256(value).hexdigest() for name, value in files.items()},
        'full_review_base_manifest_sha256': sha(base_package / 'manifest.json'),
        'full_review_citation_policy_sha256': sha(citation_policy),
        'full_review_control_flow_changes': {name: [{'before': before, 'after': after} for before, after in replacements]
                                             for name, replacements in changes.items()},
        'full_review_original_ast_equal_after_reversing_declared_changes': True,
        'full_review_preparer_sha256': sha(Path(__file__)),
        'no_partial_preselected_release': True, 'model_requests_at_preparation': 0}
    output.mkdir(parents=True)
    for name, data in files.items():
        (output / name).write_bytes(data)
    (output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', 'utf-8')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('base-package', 'citation-policy', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    prepare(args.base_package, args.citation_policy, args.output)
    print({'prepared': str(args.output), 'network_requests': 0, 'partial_release_allowed': False})


if __name__ == '__main__':
    main()
