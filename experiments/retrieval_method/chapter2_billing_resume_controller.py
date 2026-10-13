"""接续原矩阵；执行附加程序单独留痕，原controller快照保持。"""
import argparse
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Event


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


@contextmanager
def exclusive_stage_lock(path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as stream:
        stream.seek(0, 2)
        if stream.tell() == 0:
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        if os.name == 'nt':
            import msvcrt
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as error:
                raise RuntimeError('another recovery controller holds this stage') from error
        else:
            import fcntl
            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as error:
                raise RuntimeError('another recovery controller holds this stage') from error
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def closed_cell(folder, cell, plan_hash, admission, selected, stage):
    """只检查绑定及文件哈希；不载入评分语义标签。"""
    protocol_path = folder / 'protocol.json'
    if not protocol_path.exists():
        return False
    protocol = read(protocol_path)
    if protocol.get('plan_sha256') != plan_hash or protocol.get('activation_sha256') != admission:
        raise ValueError('existing cell admission/plan drift')
    if stage == 'generation' and protocol.get('formal_cell') != cell:
        raise ValueError('existing generation cell identity drift')
    if stage == 'grading' and protocol.get('cell_id') != cell['id']:
        raise ValueError('existing grading cell identity drift')
    expected = cell['question_ids'] if stage == 'generation' else [
        q for q in cell['question_ids'] if (cell['id'], q) not in selected]
    for qid in expected:
        session = folder / 'sessions' / qid
        target = session / ('result.json' if stage == 'generation' else 'score.json')
        binding_path = session / ('result-binding.json' if stage == 'generation' else 'score-binding.json')
        if not target.exists():
            return False
        if not binding_path.exists():
            raise ValueError('existing task lacks immutable binding')
        binding = read(binding_path)
        if binding.get('protocol_sha256') != sha(protocol_path):
            raise ValueError('existing task protocol binding drift')
        field = 'result_sha256' if stage == 'generation' else 'score_sha256'
        if binding.get(field) != sha(target):
            raise ValueError('existing task byte binding drift')
        if stage == 'generation' and binding.get('cell_id') != cell['id']:
            raise ValueError('existing result cell drift')
    return True


def worker_command(args, package, cell, availability):
    common = ['--plan', str(args.plan), '--resources', str(args.resources),
              '--activation', str(args.activation), '--cell', cell['id'],
              '--proxy-settings', str(args.proxy_settings), '--availability-receipt', str(availability)]
    if args.stage == 'generation':
        return [sys.executable, str(package / 'generation.py'), *common,
                '--output', str(args.generation_output / 'cells' / cell['id'])]
    return [sys.executable, str(package / 'grading.py'), *common,
            '--evaluation', str(args.evaluation), '--dataset', str(args.dataset),
            '--results', str(args.results), '--output', str(args.score_output),
            '--review-selection', str(args.review_selection)]


def verify_embedding_cache(resources, plan, cache):
    manifest_path = Path(resources['e5_manifest'])
    if sha(manifest_path) != plan['artifacts_sha256']['e5_manifest']:
        raise ValueError('registered embedding manifest drift')
    manifest = read(manifest_path)
    spec = manifest['model']
    cache = Path(spec.get('cache_folder') or cache).resolve()
    snapshot = cache / ('models--' + spec['model'].replace('/', '--')) / 'snapshots' / spec['revision']
    if not snapshot.is_dir():
        raise FileNotFoundError('registered embedding cache snapshot unavailable')
    for relative, expected in manifest['model_files'].items():
        path = (snapshot / relative).resolve()
        if not path.is_relative_to(snapshot.resolve()) or sha(path) != expected:
            raise ValueError('registered embedding model byte drift')
    return {'snapshot': str(snapshot), 'verified_files': len(manifest['model_files']), 'network_requests': 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stage', choices=['generation', 'grading'], required=True)
    for name in ('plan', 'evaluation', 'activation', 'resources', 'dataset', 'results',
                 'generation-output', 'score-output', 'review-selection', 'proxy-settings', 'hf-cache', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--availability-receipt', type=Path, action='append', default=[])
    parser.add_argument('--inspect-only', action='store_true')
    args = parser.parse_args()
    package = Path(__file__).resolve().parent
    # Frozen snapshot uses guard.py; source-module imports support offline tests.
    try:
        from guard import validate_package
    except ModuleNotFoundError:
        from chapter2_billing_resume_guard import validate_package
    manifest = validate_package(package, 'controller')
    for role, registration in [('generation', args.plan), ('grading', args.evaluation)]:
        if sha(registration) != manifest['bases'][role]['registration_sha256']:
            raise ValueError('controller arguments differ from registered execution package')
    root = Path(manifest['bases'][args.stage]['runtime'])
    sys.path.insert(0, str(root / 'experiments/retrieval_method'))
    sys.path.insert(0, str(root / 'src'))
    from chapter2_knowledge_formal_plan import validate_plan, validate_activation, activation_models, activation_identity, verify_availability
    plan = read(args.plan)
    validate_plan(plan)
    if args.stage == 'generation':
        from chapter2_knowledge_formal_runner import verify_runtime
        verify_runtime(plan)
    else:
        from chapter2_knowledge_evaluation import verify_setup
        verify_setup(read(args.evaluation), args.plan)
    activation = read(args.activation)
    validate_activation(activation, plan, sha(args.plan))
    models = activation_models(activation, plan)
    if sha(args.review_selection) != read(args.evaluation)['review_selection_sha256']:
        raise ValueError('source-first selection binding drift')
    selection = read(args.review_selection)
    if args.stage == 'grading':
        from chapter2_knowledge_formal_review import verify_selection
        selection = verify_selection(selection, plan, sha(args.plan))
    selected = {(r['cell_id'], r['question_id']) for r in selection['cases']}
    # 禁止在全量预选意见完成前以部分意见启动预选评分。
    for cell_id, qid in selected:
        if (args.score_output / cell_id / 'sessions' / qid / 'score.json').exists():
            raise ValueError('preselected scores already exist; this recovery package is unselected-only')
    if args.results.resolve() != (args.generation_output / 'cells').resolve():
        raise ValueError('generation and grading result roots differ')
    embedding = None
    if args.stage == 'generation' and any(c['model'] in models and c['method'] in {'e5', 'hybrid'} for c in plan['cells']):
        embedding = verify_embedding_cache(read(args.resources), plan, args.hf_cache)
    summary = {'schema': 'billing_resume_controller_preflight_v1', 'stage': args.stage,
        'package_manifest_sha256': sha(package / 'manifest.json'), 'plan_sha256': sha(args.plan),
        'evaluation_sha256': sha(args.evaluation), 'admitted_models': models,
        'planned_sessions': sum(len(c['question_ids']) for c in plan['cells']),
        'planned_cells': len(plan['cells']), 'preselected_scores_enabled': False,
        'registered_embedding_cache': embedding,
        'admitted_cell_state': []}
    for cell in plan['cells']:
        if cell['model'] not in models:
            continue
        folder = (args.generation_output / 'cells' if args.stage == 'generation' else args.score_output) / cell['id']
        if args.stage == 'grading' and (folder / 'protocol.json').exists():
            if read(folder / 'protocol.json').get('evaluation_sha256') != sha(args.evaluation):
                raise ValueError('existing score cell belongs to another evaluation revision')
        admission = activation_identity(activation, sha(args.activation), cell['id'])
        complete = closed_cell(folder, cell, sha(args.plan), admission, selected, args.stage)
        if args.stage == 'grading' and complete:
            for qid in cell['question_ids']:
                if (cell['id'], qid) in selected:
                    continue
                target = folder / 'sessions' / qid / 'score-binding.json'
                if read(target)['result_sha256'] != sha(args.results / cell['id'] / 'sessions' / qid / 'result.json'):
                    raise ValueError('existing score belongs to different answer')
        summary['admitted_cell_state'].append({'cell_id': cell['id'], 'complete': complete})
    if args.inspect_only:
        write_new(args.output / 'preflight.json', {**summary, 'network_requests': 0})
        print({'stage': args.stage, 'complete_cells': sum(r['complete'] for r in summary['admitted_cell_state']),
               'admitted_cells': len(summary['admitted_cell_state']), 'network_requests': 0})
        return
    if args.output.exists():
        raise FileExistsError('new recovery controller run folder required')
    from chapter2_qwen_proxy_config import settings
    base, _key = settings(args.proxy_settings)
    availability = {}
    for folder in args.availability_receipt:
        model = read(folder / 'summary.json').get('expected_model')
        if model not in models or model in availability:
            raise ValueError('one fresh availability receipt per admitted model')
        availability[model] = folder
        verify_availability(folder, model, base + '/chat/completions')
    needed_models = models if args.stage == 'generation' else ['qwen3-14b']
    if any(model not in availability for model in needed_models):
        raise ValueError('successful exact-model availability receipt required before any launch')
    stage_root = args.generation_output if args.stage == 'generation' else args.score_output
    with exclusive_stage_lock(stage_root / 'billing-resume-controller.lock'):
        write_new(args.output / 'preflight.json', summary)
        stopped = Event()
        env = dict(os.environ)
        env['PYTHONPATH'] = ''
        env['PYTHONIOENCODING'] = 'utf-8'
        env['HF_HUB_CACHE'] = str(args.hf_cache.resolve())
        complete = {r['cell_id']: r['complete'] for r in summary['admitted_cell_state']}
        def run_model(model):
            rows = []
            for cell in [c for c in plan['cells'] if c['model'] == model]:
                if stopped.is_set():
                    break
                if complete[cell['id']]:
                    rows.append({'cell_id': cell['id'], 'skipped_bound_complete_cell': True})
                    continue
                proof = availability[model if args.stage == 'generation' else 'qwen3-14b']
                folder = (args.generation_output / 'cells' if args.stage == 'generation' else args.score_output) / cell['id']
                if (folder / 'summary.json').exists():
                    prior = folder / 'summary.json'
                    history = folder / 'summary-history' / (sha(prior) + '.json')
                    history.parent.mkdir(parents=True, exist_ok=True)
                    if not history.exists():
                        history.write_bytes(prior.read_bytes())
                log = args.output / 'logs' / cell['id'] / 'execution.txt'
                log.parent.mkdir(parents=True, exist_ok=True)
                with log.open('x', encoding='utf-8') as stream:
                    result = subprocess.run(worker_command(args, package, cell, proof), env=env,
                                            stdout=stream, stderr=subprocess.STDOUT)
                state_path = folder / 'summary.json'
                state = read(state_path) if state_path.exists() else {}
                record = {'cell_id': cell['id'], 'returncode': result.returncode,
                    'summary_sha256': sha(state_path) if state_path.exists() else None,
                    'log_sha256': sha(log), 'transport_circuit_open': state.get('transport_circuit_open'),
                    'completed_sessions': len(state.get('sessions', [])) if args.stage == 'generation' else None,
                    'completed_scores': state.get('completed_scores') if args.stage == 'grading' else None}
                write_new(args.output / 'cells' / cell['id'] / 'receipt.json', record)
                rows.append(record)
                print(record, flush=True)
                if result.returncode or state.get('transport_circuit_open') is not False:
                    stopped.set()
                    break
            return {'model': model, 'records': rows}
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(run_model, model) for model in models]
            rows = [future.result() for future in as_completed(futures)]
        write_new(args.output / 'execution-summary.json', {'schema': 'billing_resume_execution_summary_v1',
            'stage': args.stage, 'package_manifest_sha256': sha(package / 'manifest.json'),
            'plan_sha256': sha(args.plan), 'preselected_scores_enabled': False,
            'stopped_for_failure': stopped.is_set(), 'models': rows,
            'full_registered_comparison_complete': False})


if __name__ == '__main__':
    main()
