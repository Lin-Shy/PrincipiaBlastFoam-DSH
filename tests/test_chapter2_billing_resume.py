"""真实离线循环验证余额恢复不会重发终止任务或改变被测请求。"""
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time

import pytest

from chapter2_autonomous_qa import PROJECT, save, sha
from chapter2_knowledge_formal_plan import RUNTIME_FILES, verify_availability
from chapter2_prepare_billing_resume import prepare, extend_source, GUARDS
import chapter2_billing_resume_guard as guard
from chapter2_billing_resume_controller import closed_cell, exclusive_stage_lock, verify_embedding_cache
from test_chapter2_knowledge_formal import plan


ENDPOINT = 'https://registered/chat/completions'


def availability(folder, started=None, model='qwen3-14b'):
    started = time.time() if started is None else started
    body = {'model': model, 'messages': [{'role': 'user', 'content': 'Return OK'}]}
    fingerprint = hashlib.sha256(json.dumps(body, separators=(',', ':')).encode()).hexdigest()
    save(folder / 'requests/00.json', {'status': 'response', 'endpoint': ENDPOINT,
        'request': body, 'request_sha256': fingerprint,
        'response': {'model': model, 'choices': [{}], 'usage': {'prompt_tokens': 10, 'completion_tokens': 2}},
        'events': [{'status': 'response', 'started_unix': started, 'seconds': .1}]})
    save(folder / 'summary.json', {'status': 'response', 'expected_model': model, 'exact_model_match': True})


def failure(folder, code=403, error=None, started=None):
    body = {'model': 'qwen3-14b'}
    save(folder / 'requests/00.json', {'status': 'http_rejected', 'endpoint': ENDPOINT,
        'request': body, 'request_sha256': hashlib.sha256(json.dumps(body, separators=(',', ':')).encode()).hexdigest(),
        'events': [{'status': 'http_error', 'attempt': 1, 'code': code, 'started_unix': time.time() - 10 if started is None else started,
                    'seconds': .1, 'provider_error_excerpt': json.dumps({'error': error or {
                        'message': 'insufficient balance', 'type': 'billing_error'}})}]})


@pytest.mark.parametrize('code,error', [(400, None), (401, None), (429, None), (503, None),
    (403, {'message': 'access denied', 'type': 'permission_error'})])
def test_other_rejections_never_receive_billing_permit(tmp_path, code, error):
    failure(tmp_path, code, error)
    assert guard.billing_failure(tmp_path, 'qwen3-14b', ENDPOINT) is None


@pytest.mark.parametrize('case', ['no_receipt', 'stale', 'before_failure', 'other_model', 'other_endpoint', 'bad_request_hash'])
def test_billing_skip_requires_fresh_later_registered_proof(tmp_path, monkeypatch, case):
    session, proof = tmp_path / 'session', tmp_path / 'proof'
    failure(session)
    save(session / 'result.json', {'status': 'http_rejected'})
    availability(proof)
    if case == 'stale':
        availability(proof, time.time() - 601)
    if case == 'before_failure':
        availability(proof, time.time() - 20)
    if case == 'bad_request_hash':
        ledger = guard.read(proof / 'requests/00.json'); ledger['request_sha256'] = '0' * 64
        save(proof / 'requests/00.json', ledger)
    package = tmp_path / 'package'; package.mkdir(); (package / 'guard.py').write_text('guard')
    save(package / 'manifest.json', {})
    monkeypatch.setattr(guard, '__file__', str(package / 'guard.py'))
    args = (session, None if case == 'no_receipt' else proof,
        'qwen3-8b' if case == 'other_model' else 'qwen3-14b',
        'other' if case == 'other_endpoint' else ENDPOINT, verify_availability, tmp_path / 'output', 'generation')
    if case in {'no_receipt', 'other_model', 'other_endpoint'}:
        assert guard.resume_billing_failure(*args) is False
    else:
        with pytest.raises(ValueError):
            guard.resume_billing_failure(*args)
    assert not (tmp_path / 'output').exists()


def package_fixture(tmp_path):
    p = plan(); p['runtime_source_sha256'] = {f: sha(PROJECT / f) for f in RUNTIME_FILES}
    public = tmp_path / 'graduation-datasets/model/questions.json'
    save(public, [{'id': q, 'question': 'Natural question ' + q} for q in p['test_ids']])
    tokenizer = tmp_path / 'tokenizer'; save(tokenizer / 'artifact-binding.json', {})
    p['questions_sha256'] = p['artifacts_sha256']['questions'] = sha(public)
    p['artifacts_sha256']['tokenizer_qwen3-14b'] = sha(tokenizer / 'artifact-binding.json')
    plan_path = tmp_path / 'plan.json'; save(plan_path, p)
    evaluation = tmp_path / 'evaluation.json'
    save(evaluation, {'plan_sha256': sha(plan_path), 'runtime_source_sha256': {
        'experiments/retrieval_method/chapter2_score_knowledge_formal.py': sha(PROJECT / 'experiments/retrieval_method/chapter2_score_knowledge_formal.py')}})
    package = tmp_path / 'package'; prepare(plan_path, evaluation, package, PROJECT, PROJECT)
    resources = {name: str(tmp_path / 'scoring/annotations.json') for name in
        ('questions', 'corpus', 'corpus_manifest', 'source_map', 'e5_manifest', 'graph_full',
         'graph_no_cross', 'graph_no_conditions', 'graph_no_extension', 'tokenizer_qwen3-8b', 'tokenizer_qwen3-14b',
         'materials', 'review_receipt')}
    resources.update(schema='knowledge_qa_local_resource_map_v1', questions=str(public), **{'tokenizer_qwen3-14b': str(tokenizer)})
    save(tmp_path / 'scoring/annotations.json', 'GOLD_MUST_NEVER_ENTER_QA')
    resource_path = tmp_path / 'resources.json'; save(resource_path, resources)
    activation = tmp_path / 'activation.json'
    save(activation, {'schema': 'knowledge_qa_formal_activation_v1', 'status': 'accepted_for_formal_execution',
        'plan_sha256': sha(plan_path), 'acceptance_sha256': 'b' * 64, 'judge_protocol_sha256': 'c' * 64,
        'cell_ids': [c['id'] for c in p['cells']]})
    return package, plan_path, resource_path, activation


def test_export_preserves_all_original_ast_except_declared_condition(tmp_path):
    package, *_ = package_fixture(tmp_path)
    manifest = guard.validate_package(package, 'controller')
    for role, name in [('generation', 'chapter2_knowledge_formal_runner.py'), ('grading', 'chapter2_score_knowledge_formal.py')]:
        original = (PROJECT / 'experiments/retrieval_method' / name).read_text('utf-8')
        changed = extend_source(original, role)
        assert ast.dump(ast.parse(changed.replace(GUARDS[role][1], GUARDS[role][0]))) == ast.dump(ast.parse(original))
        assert manifest['execution_differences'][role]['original_executor_sha256'] == sha(PROJECT / 'experiments/retrieval_method' / name)
    with pytest.raises(FileExistsError):
        prepare(tmp_path / 'plan.json', tmp_path / 'evaluation.json', package, PROJECT, PROJECT)
    (package / 'generation.py').write_text('altered')
    with pytest.raises(ValueError, match='program drift'):
        guard.validate_package(package, 'generation')


def generation_program(package, arguments, calls_path, fail=False, extended=False):
    return f'''import sys,json,hashlib,time,importlib.util
from pathlib import Path
sys.path.insert(0,{str(package)!r})
sys.path.insert(0,{str(PROJECT/'experiments/retrieval_method')!r})
sys.path.insert(0,{str(PROJECT/'src')!r})
spec=importlib.util.spec_from_file_location('worker',{str(package/'generation.py' if extended else PROJECT/'experiments/retrieval_method/chapter2_knowledge_formal_runner.py')!r})
runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
runner.settings=lambda _:("https://registered","not-a-real-key")
runner.load_tokenizer=lambda *args:(lambda _:100,{{"model":"qwen3-14b"}})
calls=[]
class FakeClient:
 def __init__(self,endpoint,key,folder):self.folder=folder;self.endpoint=endpoint
 def __call__(self,body,turn):
  assert 'GOLD_MUST_NEVER_ENTER_QA' not in json.dumps(body)
  calls.append(body)
  if {fail!r}:
   value={{'status':'http_rejected','endpoint':self.endpoint,'request':body,
    'request_sha256':hashlib.sha256(json.dumps(body,ensure_ascii=False,separators=(',',':')).encode()).hexdigest(),
    'events':[{{'attempt':1,'status':'http_error','code':403,'started_unix':time.time()-1,'seconds':.01,
    'provider_error_excerpt':json.dumps({{'error':{{'message':'insufficient balance','type':'billing_error'}}}})}}]}}
   runner.save(self.folder/f'{{turn:02d}}.json',value);return value
  return {{'status':'response','response':{{'model':body['model'],'usage':{{'completion_tokens':10}},
   'choices':[{{'finish_reason':'stop','message':{{'content':json.dumps({{'action':'final','answer':'Bound response','references':[]}})}}}}]}}}}
runner.RecordedQwenClient=FakeClient
sys.argv={arguments!r};runner.main()
Path({str(calls_path)!r}).write_text(json.dumps(calls))
'''


@pytest.mark.parametrize('new_billing_failure', [False, True])
def test_real_generation_reuses_old_failure_and_only_sends_unattempted_requests(tmp_path, new_billing_failure):
    package, plan_path, resources, activation = package_fixture(tmp_path)
    output, calls = tmp_path / 'out', tmp_path / 'calls.json'
    args = ['worker', '--plan', str(plan_path), '--resources', str(resources), '--activation', str(activation),
        '--cell', 'main/qwen3-14b_none/r01', '--proxy-settings', 'not-read', '--output', str(output)]
    def run(argv, fail=False, extended=False):
        result = subprocess.run([sys.executable, '-c', generation_program(package, argv, calls, fail, extended)],
            capture_output=True, text=True, encoding='utf-8')
        assert result.returncode == 0, result.stderr
        return json.loads(calls.read_text())
    assert len(run(args, fail=True)) == 1
    protected = {p: sha(p) for p in [output / 'protocol.json', output / 'sessions/Q0/result.json',
        output / 'sessions/Q0/result-binding.json', output / 'sessions/Q0/requests/00.json']}
    # No proof cannot skip old403 and sends no further API request.
    assert run(args, extended=True) == []
    proof = tmp_path / 'availability'; availability(proof)
    argv = args + ['--availability-receipt', str(proof)]
    new_calls = run(argv, fail=new_billing_failure, extended=True)
    assert len(new_calls) == (1 if new_billing_failure else 199)
    for path, digest in protected.items():
        assert sha(path) == digest
    summary = guard.read(output / 'summary.json')
    assert summary['sessions'][0]['status'] == 'http_rejected'
    assert summary['transport_circuit_open'] is new_billing_failure
    assert len(summary['sessions']) == (2 if new_billing_failure else 200)
    if not new_billing_failure:
        baseline = tmp_path / 'baseline'
        baseline_calls = run(args[:-1] + [str(baseline)])
        assert new_calls == baseline_calls[1:]
        assert run(argv, extended=True) == []
    assert len(list((output / 'availability-amendments').rglob('Q0.json'))) == 1


def test_closed_cell_checks_bytes_without_parsing_score_labels(tmp_path):
    cell = {'id': 'registered', 'question_ids': ['Q0', 'Q1']}
    save(tmp_path / 'protocol.json', {'cell_id': 'registered', 'plan_sha256': 'plan', 'activation_sha256': 'admitted'})
    score = tmp_path / 'sessions/Q0/score.json'; score.parent.mkdir(parents=True)
    # The payload need not be parseable by a metadata-only completion check.
    score.write_text('PRIVATE_SCORE_LABEL_NOT_PARSED')
    save(score.with_name('score-binding.json'), {'score_sha256': sha(score), 'protocol_sha256': sha(tmp_path / 'protocol.json')})
    assert closed_cell(tmp_path, cell, 'plan', 'admitted', {('registered', 'Q1')}, 'grading')
    score.write_text('altered')
    with pytest.raises(ValueError, match='byte binding'):
        closed_cell(tmp_path, cell, 'plan', 'admitted', {('registered', 'Q1')}, 'grading')


def test_same_stage_controller_cannot_lock_twice(tmp_path):
    with exclusive_stage_lock(tmp_path / 'lease'):
        with pytest.raises(RuntimeError, match='another recovery'):
            with exclusive_stage_lock(tmp_path / 'lease'):
                pytest.fail('duplicate controller acquired lock')


def test_embedding_cache_must_match_frozen_revision_and_model_bytes(tmp_path):
    model = tmp_path / 'cache/models--fixture/snapshots/frozen/model.bin'
    model.parent.mkdir(parents=True); model.write_bytes(b'frozen weights')
    manifest = tmp_path / 'index.json'; save(manifest, {'model': {'model': 'fixture', 'revision': 'frozen'},
        'model_files': {'model.bin': sha(model)}})
    resources = {'e5_manifest': str(manifest)}; p = {'artifacts_sha256': {'e5_manifest': sha(manifest)}}
    assert verify_embedding_cache(resources, p, tmp_path / 'cache')['verified_files'] == 1
    with pytest.raises(FileNotFoundError): verify_embedding_cache(resources, p, tmp_path / 'wrong-cache')
    model.write_bytes(b'changed')
    with pytest.raises(ValueError, match='model byte drift'): verify_embedding_cache(resources, p, tmp_path / 'cache')


def test_generation_circuit_only_stops_its_exact_model_queue(tmp_path, monkeypatch):
    import chapter2_billing_resume_controller as controller
    import chapter2_prepare_billing_resume as preparer
    package, plan_path, resources, activation = package_fixture(tmp_path)
    p = guard.read(plan_path)
    from chapter2_knowledge_formal_plan import digest
    from chapter2_knowledge_formal_review import selected_cases
    selection = tmp_path / 'selection.json'
    save(selection, {'schema': 'prospective_knowledge_qa_original_review_v1', 'plan_sha256': sha(plan_path),
        'policy_sha256': digest(p['independent_review']), 'implementation_sha256': 'a' * 64,
        'cases': [{'review_id': format(i, '032x'), 'cell_id': c, 'question_id': q}
                  for i, (c, q) in enumerate(selected_cases(p))]})
    evaluation = tmp_path / 'evaluation.json'; e = guard.read(evaluation)
    e['review_selection_sha256'] = sha(selection); save(evaluation, e)
    package2 = tmp_path / 'package2'; preparer.prepare(plan_path, evaluation, package2, PROJECT, PROJECT)
    monkeypatch.setattr(controller, '__file__', str(package2 / 'controller.py'))
    monkeypatch.setattr(controller, 'verify_embedding_cache', lambda *args: {'verified_files': 0, 'network_requests': 0})
    import chapter2_qwen_proxy_config
    monkeypatch.setattr(chapter2_qwen_proxy_config, 'settings', lambda _: ('https://registered', 'test-key'))
    calls = []
    def worker(command, **kwargs):
        cell_id = command[command.index('--cell') + 1]
        calls.append(cell_id)
        output = Path(command[command.index('--output') + 1])
        save(output / 'summary.json', {'transport_circuit_open': 'qwen3-8b_' in cell_id, 'sessions': []})
        return type('Result', (), {'returncode': 0})()
    monkeypatch.setattr(controller.subprocess, 'run', worker)
    a8, a14 = tmp_path / 'proof8', tmp_path / 'proof14'
    availability(a8, model='qwen3-8b'); availability(a14)
    args = ['controller', '--stage', 'generation', '--plan', str(plan_path), '--evaluation', str(evaluation),
        '--activation', str(activation), '--resources', str(resources), '--dataset', str(tmp_path / 'dataset'),
        '--results', str(tmp_path / 'gen/cells'), '--generation-output', str(tmp_path / 'gen'),
        '--score-output', str(tmp_path / 'scores'), '--review-selection', str(selection), '--proxy-settings', 'not-read',
        '--hf-cache', str(tmp_path / 'cache'), '--output', str(tmp_path / 'run'),
        '--availability-receipt', str(a8), '--availability-receipt', str(a14)]
    monkeypatch.setattr(sys, 'argv', args); controller.main()
    assert sum('qwen3-8b_' in c for c in calls) == 1
    assert sum('qwen3-14b_' in c for c in calls) == 75
    summary = guard.read(tmp_path / 'run/execution-summary.json')
    assert summary['stopped_for_failure'] and not summary['full_registered_comparison_complete']


def test_real_grading_keeps_billing_unknown_and_preselected_gate(tmp_path, monkeypatch):
    import chapter2_score_knowledge_formal as original
    import chapter2_knowledge_evaluation as evaluation_module
    from chapter2_partial_answer_scoring import COVERAGE_PROMPT, SOURCE_PROMPT
    from chapter2_knowledge_formal_review import selected_cases
    from chapter2_knowledge_formal_plan import digest
    from principia_core.retrieval.knowledge_qa import MANIFEST_SCHEMA, wire
    p = plan(); p['runtime_source_sha256'] = {f: sha(PROJECT / f) for f in RUNTIME_FILES}
    dataset = tmp_path / 'dataset'; raw = tmp_path / 'raw'
    source = raw / 'manual/topic.md'; source.parent.mkdir(parents=True); source.write_text('Supported original.\n')
    manifest = tmp_path / 'corpus.json'; save(manifest, {'schema': MANIFEST_SCHEMA,
        'files': [{'path': 'manual/topic.md', 'sha256': sha(source), 'bytes': source.stat().st_size, 'lines': 1}]})
    questions = [{'id': q, 'question': 'Question ' + q} for q in p['test_ids']]
    annotations = [{'id': q, 'split_group': 'group-' + str(i % 15), 'required_evidence_ids': ['E'],
        'required_points': [{'id': 'K', 'claim': 'Supported original.', 'weight': 1}],
        'labels': {'evidence_integration': 'single', 'condition_discrimination': False},
        'applicability': 'None', 'acceptable_answer_range': 'Bounded', 'critical_errors': []}
        for i, q in enumerate(p['test_ids'])]
    for path, value in [('model/questions.json', questions), ('scoring/annotations.json', annotations),
            ('scoring/evidence.json', {'E': {'path': 'manual/topic.md', 'line_start': 1, 'line_end': 1,
                'file_sha256': sha(source), 'excerpt': 'Supported original.'}})]:
        save(dataset / path, value)
    save(dataset / 'dataset-seal.json', {'files': {f: sha(dataset / f) for f in
        ['model/questions.json', 'scoring/annotations.json', 'scoring/evidence.json']}})
    p['dataset_seal_sha256'] = sha(dataset / 'dataset-seal.json')
    plan_path = tmp_path / 'plan.json'; save(plan_path, p)
    runtime = tmp_path / 'runtime'; runtime_files = ['chapter2_knowledge_evaluation.py', 'chapter2_score_knowledge_formal.py']
    for f in runtime_files:
        dest = runtime / 'experiments/retrieval_method' / f; dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes((PROJECT / 'experiments/retrieval_method' / f).read_bytes())
    settings = {'rubric_version': 'source_free_v7', 'judge_model': 'qwen3-14b',
        'corpus_manifest_sha256': sha(manifest), 'judge_prompt': {'candidate_only_coverage': COVERAGE_PROMPT,
        'independent_source_audit': SOURCE_PROMPT}, 'tokenizer': {'model': 'qwen3-14b'}}
    accepted = tmp_path / 'accepted_measurement/protocol.json'; save(accepted, {**settings, 'source_sha256': {}})
    selection = tmp_path / 'selection.json'; save(selection, {'schema': 'prospective_knowledge_qa_original_review_v1',
        'plan_sha256': sha(plan_path), 'policy_sha256': digest(p['independent_review']), 'implementation_sha256': 'd' * 64,
        'cases': [{'review_id': format(i, '032x'), 'cell_id': c, 'question_id': q} for i, (c, q) in enumerate(selected_cases(p))]})
    setup = {'schema': 'knowledge_qa_formal_evaluation_preparation_v1', 'plan_sha256': sha(plan_path),
        'judge_settings': settings, 'runtime_source_sha256': {'experiments/retrieval_method/' + f:
        sha(runtime / 'experiments/retrieval_method' / f) for f in runtime_files},
        'accepted_judge_source_sha256': {}, 'dataset_seal_sha256': p['dataset_seal_sha256'],
        'accepted_judge_protocol_file': 'accepted_measurement/protocol.json',
        'accepted_judge_protocol_sha256': sha(accepted), 'review_selection_sha256': sha(selection)}
    evaluation_path = tmp_path / 'evaluation.json'; save(evaluation_path, setup)
    activation = tmp_path / 'activation.json'; save(activation, {'schema': 'knowledge_qa_formal_activation_v1',
        'status': 'accepted_for_formal_execution', 'plan_sha256': sha(plan_path), 'acceptance_sha256': 'b' * 64,
        'judge_protocol_sha256': sha(accepted), 'cell_ids': [c['id'] for c in p['cells']]})
    resources = tmp_path / 'resources.json'; save(resources, {'corpus_manifest': str(manifest), 'corpus': str(raw),
        'tokenizer_qwen3-14b': str(tmp_path / 'tokenizer')})
    cell = next(c for c in p['cells'] if c['id'] == 'main/qwen3-14b_none/r01')
    unselected = [q for q in p['test_ids'] if q not in p['independent_review']['question_ids']][:2]
    selected = p['independent_review']['question_ids'][0]
    results = tmp_path / 'results'; protocol = results / cell['id'] / 'protocol.json'
    save(protocol, {'schema': 'activated_knowledge_qa_formal_cell_v1', 'formal_cell': cell,
        'plan_sha256': sha(plan_path), 'activation_sha256': sha(activation)})
    for qid in [selected, *unselected]:
        path = protocol.parent / 'sessions' / qid / 'result.json'
        save(path, {'formal_result': True, 'formal_cell_id': cell['id'], 'question': next(q for q in questions if q['id'] == qid),
            'protocol_sha256': sha(protocol), 'status': 'answered', 'answer': 'Supported original.', 'references': [], 'tool_events': []})
        save(path.with_name('result-binding.json'), {'result_sha256': sha(path), 'protocol_sha256': sha(protocol), 'cell_id': cell['id']})
    package = tmp_path / 'package'; prepare(plan_path, evaluation_path, package, PROJECT, runtime)
    spec = importlib.util.spec_from_file_location('guard', package / 'guard.py'); package_guard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(package_guard); monkeypatch.setitem(sys.modules, 'guard', package_guard)
    spec = importlib.util.spec_from_file_location('billing_grader', package / 'grading.py'); extended = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(extended)
    monkeypatch.setattr(evaluation_module, 'PROJECT', runtime)
    calls, reject = [], [True]
    class Client:
        def __init__(self, endpoint, key, folder): self.folder = folder
        def __call__(self, body, index):
            calls.append(body)
            value = json.loads(body['messages'][1]['content'])
            if reject[0]:
                result = {'status': 'http_rejected', 'events': [{'attempt': 1, 'status': 'http_error', 'code': 403,
                    'started_unix': time.time() - 1, 'seconds': .01, 'provider_error_excerpt': json.dumps({'error': {
                        'message': 'insufficient balance', 'type': 'billing_error'}})}]}
            else:
                answer = ({'verdict': 'full', 'answer_segment_ids': [s['id'] for s in value['premise_segments']], 'reason': 'Conveys claim'}
                    if 'hypothesis' in value else {'segments': [{'id': s['id'], 'verdict': 'supported', 'reason': 'Original support'}
                        for s in value['candidate_segments']], 'condition': {'verdict': 'not_applicable', 'reason': 'None'}})
                result = {'status': 'response', 'events': [], 'response': {'model': body['model'],
                    'usage': {'prompt_tokens': 100, 'completion_tokens': 100},
                    'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(answer)}}]}}
            result.update(endpoint=ENDPOINT, request=body, request_sha256=hashlib.sha256(wire(body).encode()).hexdigest())
            save(self.folder / f'{index:02d}.json', result); return result
    for module in [original, extended]:
        monkeypatch.setattr(module, 'load_tokenizer', lambda *args: (lambda _: 100, {'model': 'qwen3-14b'}))
        monkeypatch.setattr(module, 'settings', lambda _: ('https://registered', 'test-key'))
        monkeypatch.setattr(module, 'RecordedQwenClient', Client)
    scores = tmp_path / 'scores'
    args = ['grader', '--evaluation', str(evaluation_path), '--plan', str(plan_path), '--activation', str(activation),
        '--resources', str(resources), '--dataset', str(dataset), '--results', str(results), '--output', str(scores),
        '--cell', cell['id'], '--proxy-settings', 'not-read', '--review-selection', str(selection)]
    monkeypatch.setattr(sys, 'argv', args); original.main(); assert len(calls) == 1
    failed = scores / cell['id'] / 'sessions' / unselected[0] / 'score.json'
    protected = {p: sha(p) for p in [failed, failed.with_name('score-binding.json'), scores / cell['id'] / 'protocol.json']}
    assert guard.read(failed)['metrics'] == {'complete_valid_answer': None, 'complete_lower': 0, 'complete_upper': 1}
    reject[0] = False; calls.clear(); extended.main(); assert calls == []
    proof = tmp_path / 'proof'; availability(proof)
    monkeypatch.setattr(sys, 'argv', args + ['--availability-receipt', str(proof)])
    extended.main(); resumed_calls = list(calls); assert len(resumed_calls) == 2
    for path, digest_value in protected.items(): assert sha(path) == digest_value
    assert not (scores / cell['id'] / 'sessions' / selected / 'score.json').exists()
    assert guard.read(failed)['status'] == 'judge_unknown' and guard.read(failed)['reason'] == 'http_rejected'
    calls.clear(); extended.main(); assert calls == []
    baseline_args = args.copy(); baseline_args[baseline_args.index('--output') + 1] = str(tmp_path / 'baseline')
    monkeypatch.setattr(sys, 'argv', baseline_args); original.main(); assert len(calls) == 4
    assert resumed_calls == calls[2:]
