"""从原冻结执行器导出仅扩展余额恢复条件的独立执行包。"""
import argparse
import ast
import hashlib
import json
from pathlib import Path


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


GUARDS = {
    'generation': (
        "resumed and result['status']=='transport_error' and a.availability_receipt is not None",
        "resumed and (result['status']=='transport_error' or (result['status']=='http_rejected' and "
        "resume_billing_failure(folder,a.availability_receipt,cell['model'],protocol['endpoint'],"
        "verify_availability,a.output,'generation'))) and a.availability_receipt is not None"),
    'grading': (
        "resumed and score['reason'] == 'transport_error' and args.availability_receipt is not None",
        "resumed and (score['reason'] == 'transport_error' or (score['reason'] == 'http_rejected' and "
        "resume_billing_failure(folder,args.availability_receipt,'qwen3-14b',protocol['endpoint'],"
        "verify_availability,target.parent,'grading'))) and args.availability_receipt is not None")}


def extend_source(original, role):
    before, after = GUARDS[role]
    if original.count(before) != 1:
        raise ValueError('expected single frozen resume condition absent')
    extended = original.replace(before, after)
    # 撤回唯一条件替换后整个AST相同；不改请求构建、绑定、失败结果或评分函数。
    if ast.dump(ast.parse(extended.replace(after, before))) != ast.dump(ast.parse(original)):
        raise ValueError('unexpected execution source change')
    return extended


def bootstrap(role):
    prefix = ("# Execution extension is recorded separately from the original measurement protocol.\n"
            "from pathlib import Path as _BillingPath\n"
            "import sys as _BillingSys\n"
            "from guard import validate_package, resume_billing_failure\n"
            f"_billing_manifest = validate_package(_BillingPath(__file__).parent, {role!r})\n"
            f"_billing_root = _BillingPath(_billing_manifest['bases'][{role!r}]['runtime'])\n"
            "_BillingSys.path.insert(0,str(_billing_root/'experiments/retrieval_method'))\n"
            "_BillingSys.path.insert(0,str(_billing_root/'src'))\n")
    if role == 'grading':
        prefix += ("if any(a.split('=')[0] in {'--review-pack','--review-verdicts'} for a in _BillingSys.argv[1:]):\n"
                   "    raise ValueError('billing execution package only grades non-preselected answers')\n")
    return prefix


def prepare(plan_path, evaluation_path, output, generation_runtime=None, grading_runtime=None):
    plan_path, evaluation_path, output = map(lambda p: Path(p).resolve(), (plan_path, evaluation_path, output))
    if output.exists():
        raise FileExistsError('new immutable billing execution package required')
    plan, evaluation = read(plan_path), read(evaluation_path)
    if evaluation['plan_sha256'] != sha(plan_path):
        raise ValueError('evaluation must bind original generation plan')
    bases = {}
    for role, registration, value, supplied in [
            ('generation', plan_path, plan, generation_runtime),
            ('grading', evaluation_path, evaluation, grading_runtime)]:
        root = Path(supplied).resolve() if supplied is not None else registration.parent / 'runtime'
        for relative, expected in value['runtime_source_sha256'].items():
            source = (root / relative).resolve()
            if not source.is_relative_to(root) or sha(source) != expected:
                raise ValueError('base runtime differs from registered bytes')
        bases[role] = {'runtime': str(root), 'registration_file': str(registration),
            'registration_sha256': sha(registration), 'runtime_source_sha256': value['runtime_source_sha256']}
    app = Path(__file__).resolve().parent
    files = {'guard.py': (app / 'chapter2_billing_resume_guard.py').read_bytes(),
             'controller.py': (app / 'chapter2_billing_resume_controller.py').read_bytes()}
    diffs = {}
    for role, filename in [('generation', 'chapter2_knowledge_formal_runner.py'),
                           ('grading', 'chapter2_score_knowledge_formal.py')]:
        original_path = Path(bases[role]['runtime']) / 'experiments/retrieval_method' / filename
        original = original_path.read_text(encoding='utf-8')
        files[role + '.py'] = (bootstrap(role) + extend_source(original, role)).encode('utf-8')
        diffs[role] = {'original_executor_sha256': sha(original_path),
            'allowed_condition_before': GUARDS[role][0], 'allowed_condition_after': GUARDS[role][1],
            'entire_original_ast_equal_after_reversing_condition': True}
    manifest = {'schema': 'knowledge_qa_billing_execution_extension_v1', 'bases': bases,
        'files_sha256': {k: hashlib.sha256(v).hexdigest() for k, v in files.items()},
        'execution_differences': diffs, 'grading_mode': 'non_preselected_only',
        'original_measurement_protocols_preserved': True, 'new_failures_still_stop': True,
        'previous_terminal_tasks_never_reissued': True, 'model_requests_at_preparation': 0,
        'preparer_sha256': sha(Path(__file__))}
    output.mkdir(parents=True)
    for name, data in files.items():
        (output / name).write_bytes(data)
    (output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('plan', 'evaluation', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    prepare(args.plan, args.evaluation, args.output)
    print({'prepared': str(args.output), 'network_requests': 0, 'grading': 'non_preselected_only'})


if __name__ == '__main__':
    main()
