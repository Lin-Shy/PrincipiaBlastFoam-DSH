"""完整合成队列及真实冻结评分循环；不发起网络、不生成实际实验标签。"""
import copy
import importlib.util
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from chapter2_autonomous_qa import PROJECT, save, sha
from chapter2_knowledge_formal_plan import RUNTIME_FILES, digest, cells as registered_cells, review_policy
from chapter2_knowledge_formal_review import selected_cases, masked_item
from chapter2_citation_original_review import masked_case
from chapter2_answer_scoring import scoring_payload
from chapter2_prepare_billing_resume import prepare as prepare_base
from chapter2_prepare_full_review_grading import prepare, transform, FULL_MODE
from chapter2_full_review_release import verify_complete_release
from principia_core.retrieval.knowledge_qa import MANIFEST_SCHEMA, FrozenKnowledgeCorpus
from test_chapter2_knowledge_formal import plan


@pytest.fixture
def full_cohort(tmp_path, monkeypatch):
    import chapter2_knowledge_evaluation as evaluation_module
    from chapter2_partial_answer_scoring import COVERAGE_PROMPT, SOURCE_PROMPT
    p = plan()
    p['diagnostic_ids'] = p['test_ids'][:4] + p['test_ids'][40:52]
    p['independent_review'] = review_policy(p['diagnostic_ids'])
    p['cells'] = registered_cells(p['test_ids'], p['budget_ids'], p['diagnostic_ids'])
    p['runtime_source_sha256'] = {f: sha(PROJECT / f) for f in RUNTIME_FILES}
    dataset, raw = tmp_path / 'dataset', tmp_path / 'raw'
    source = raw / 'manual/topic.md'
    source.parent.mkdir(parents=True)
    source.write_text('Supported original.\n', 'utf-8')
    manifest = tmp_path / 'corpus.json'
    save(manifest, {'schema': MANIFEST_SCHEMA, 'files': [{'path': 'manual/topic.md',
        'sha256': sha(source), 'bytes': source.stat().st_size, 'lines': 1}]})
    questions = {q: {'id': q, 'question': 'Question ' + q} for q in p['test_ids']}
    annotations = {q: {'id': q, 'split_group': 'group-' + str(i % 15), 'required_evidence_ids': ['E'],
        'required_points': [{'id': 'K', 'claim': 'Supported original.', 'weight': 1}],
        'labels': {'evidence_integration': 'single', 'condition_discrimination': False},
        'applicability': 'None', 'acceptable_answer_range': 'Bounded', 'critical_errors': []}
        for i, q in enumerate(p['test_ids'])}
    evidence = {'E': {'path': 'manual/topic.md', 'line_start': 1, 'line_end': 1,
        'file_sha256': sha(source), 'excerpt': 'Supported original.'}}
    for path, value in [('model/questions.json', list(questions.values())),
            ('scoring/annotations.json', list(annotations.values())), ('scoring/evidence.json', evidence)]:
        save(dataset / path, value)
    save(dataset / 'dataset-seal.json', {'files': {f: sha(dataset / f) for f in
        ['model/questions.json', 'scoring/annotations.json', 'scoring/evidence.json']}})
    p['dataset_seal_sha256'] = sha(dataset / 'dataset-seal.json')
    p['artifacts_sha256']['corpus_manifest'] = sha(manifest)
    plan_path = tmp_path / 'plan.json'
    save(plan_path, p)
    runtime = tmp_path / 'runtime'
    runtime_files = ['chapter2_score_knowledge_formal.py', 'chapter2_knowledge_formal_review.py',
                     'chapter2_analyze_knowledge_formal.py', 'chapter2_knowledge_evaluation.py']
    for name in runtime_files:
        target = runtime / 'experiments/retrieval_method' / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((PROJECT / 'experiments/retrieval_method' / name).read_bytes())
    monkeypatch.setattr(evaluation_module, 'PROJECT', runtime)
    settings = {'rubric_version': 'source_free_v7', 'judge_model': 'qwen3-14b',
        'corpus_manifest_sha256': sha(manifest), 'judge_prompt': {'candidate_only_coverage': COVERAGE_PROMPT,
        'independent_source_audit': SOURCE_PROMPT}, 'tokenizer': {'model': 'qwen3-14b'}}
    accepted = tmp_path / 'accepted_measurement/protocol.json'
    save(accepted, {**settings, 'source_sha256': {}})
    selection_path = tmp_path / 'selection.json'
    selection = {'schema': 'prospective_knowledge_qa_original_review_v1',
        'plan_sha256': sha(plan_path), 'policy_sha256': digest(p['independent_review']),
        'implementation_sha256': 'd' * 64, 'cases': [{'review_id': format(i, '032x'),
        'cell_id': c, 'question_id': q} for i, (c, q) in enumerate(selected_cases(p))]}
    save(selection_path, selection)
    setup = {'schema': 'knowledge_qa_formal_evaluation_preparation_v1', 'plan_sha256': sha(plan_path),
        'judge_settings': settings, 'runtime_source_sha256': {'experiments/retrieval_method/' + name:
            sha(runtime / 'experiments/retrieval_method' / name) for name in runtime_files},
        'accepted_judge_source_sha256': {}, 'dataset_seal_sha256': p['dataset_seal_sha256'],
        'accepted_judge_protocol_file': 'accepted_measurement/protocol.json',
        'accepted_judge_protocol_sha256': sha(accepted), 'review_selection_sha256': sha(selection_path)}
    evaluation = tmp_path / 'evaluation.json'
    save(evaluation, setup)
    activation = tmp_path / 'activation.json'
    save(activation, {'schema': 'knowledge_qa_formal_activation_v1', 'status': 'accepted_for_formal_execution',
        'plan_sha256': sha(plan_path), 'acceptance_sha256': 'b' * 64,
        'judge_protocol_sha256': sha(accepted), 'cell_ids': [c['id'] for c in p['cells']]})
    resources = tmp_path / 'resources.json'
    save(resources, {'corpus_manifest': str(manifest), 'corpus': str(raw),
                    'tokenizer_qwen3-14b': str(tmp_path / 'tokenizer')})
    policy = tmp_path / 'citation_policy/policy.json'
    citation_hashes = {}
    for name in ['chapter2_citation_original_review.py', 'chapter2_citation_support.py']:
        relative = 'experiments/retrieval_method/' + name
        target = policy.parent / 'runtime' / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((PROJECT / relative).read_bytes())
        citation_hashes[relative] = sha(target)
    save(policy, {'schema': 'prospective_citation_original_review_policy_v1', 'plan_sha256': sha(plan_path),
        'selection_sha256': sha(selection_path), 'planned_cases': len(selection['cases']),
        'primary_judge_changed': False, 'failed_automatic_citation_judge_adopted': False,
        'runtime_source_sha256': citation_hashes})
    corpus = FrozenKnowledgeCorpus(raw, manifest)
    cells = {c['id']: c for c in p['cells']}
    results, scores = tmp_path / 'results', tmp_path / 'scores'
    primary, citations, keys, opinions, primary_rows = [], [], [], [], []
    for row in selection['cases']:
        cid, qid, rid = row['cell_id'], row['question_id'], row['review_id']
        protocol = results / cid / 'protocol.json'
        if not protocol.exists():
            save(protocol, {'schema': 'activated_knowledge_qa_formal_cell_v1', 'formal_cell': cells[cid],
                'plan_sha256': sha(plan_path), 'activation_sha256': sha(activation)})
        result = {'formal_result': True, 'formal_cell_id': cid, 'question': questions[qid],
            'protocol_sha256': sha(protocol), 'status': 'answered', 'answer': 'Supported original.',
            'references': [{'path': 'manual/topic.md', 'start': 1, 'end': 1}],
            'references_delivered': True, 'tool_events': [{'delivered_original_lines': [{'path': 'manual/topic.md', 'line': 1}]}]}
        path = protocol.parent / 'sessions' / qid / 'result.json'
        save(path, result)
        save(path.with_name('result-binding.json'), {'result_sha256': sha(path), 'protocol_sha256': sha(protocol), 'cell_id': cid})
        payload = scoring_payload(questions[qid]['question'], annotations[qid], evidence, corpus,
                                  result['answer'], result['tool_events'][0]['delivered_original_lines'])
        primary.append(masked_item(rid, result, payload))
        citations.append(masked_case(rid, questions[qid]['question'], result, corpus))
        keys.append({**row, 'result_file': str(path.resolve()), 'result_sha256': sha(path)})
        primary_rows.append({'review_id': rid, 'complete_valid_answer': None, 'reason': 'Unresolved synthetic opinion.', 'source_basis': []})
        opinions.append({'review_id': rid, 'segments': [{'id': 'A1', 'verdict': 'unknown', 'support': [],
            'reason': 'Unresolved synthetic opinion.'}], 'references': [{'id': 'R1', 'verdict': 'unknown',
            'segment_ids': [], 'reason': 'Unresolved synthetic opinion.'}]})
    primary_pack, citation_pack = tmp_path / 'primary', tmp_path / 'citations'
    for pack, inputs, name, schema in [(primary_pack, primary, 'pack-receipt.json', 'formal_method_masked_original_review_pack_v1'),
            (citation_pack, citations, 'receipt.json', 'masked_citation_original_review_pack_v1')]:
        save(pack / 'evaluation_only/inputs.json', inputs)
        save(pack / 'evaluation_only/blind-key.json', keys)
        save(pack / name, {'schema': schema, 'plan_sha256': sha(plan_path), 'selection_sha256': sha(selection_path),
            'planned_cases': len(keys), 'available_cases': len(keys), 'pending_review_ids': [], 'automatic_scores_read': 0,
            'inputs_sha256': sha(pack / 'evaluation_only/inputs.json'), 'blind_key_sha256': sha(pack / 'evaluation_only/blind-key.json'),
            'implementation_sha256': setup['runtime_source_sha256']['experiments/retrieval_method/chapter2_knowledge_formal_review.py'],
            'formal_result': True, 'gold_points_read': False, 'policy_sha256': sha(policy),
            'activation_sha256': sha(activation), 'declared_primary_scores_root': str(scores.resolve())})
    verdicts, citation_verdicts = primary_pack / 'opinions.json', citation_pack / 'opinions.json'
    save(verdicts, {'schema': 'independent_original_answer_review_v1', 'reviewer': 'Codex (AI)',
        'human_truth': False, 'reference_before_automatic_scores': True, 'rows': primary_rows})
    save(citation_verdicts, {'schema': 'source_first_citation_original_review_v1', 'reviewer': 'Codex (AI)',
        'human_truth': False, 'before_automatic_scores': True, 'gold_points_read': False, 'rows': opinions})
    # Reproduce004's real source-snapshot lineage; primary keys must point
    # to the immutable view rather than the growing original result root.
    snapshot_parent = tmp_path / 'source_snapshot'
    snapshot_root = snapshot_parent / 'evaluation_only/results'
    snapshot_hashes, snapshot_rows, primary_keys = {}, [], []
    for key in keys:
        cid, qid = key['cell_id'], key['question_id']
        relative = Path(cid) / 'sessions' / qid / 'result.json'
        for item in [Path(cid) / 'protocol.json', relative, relative.with_name('result-binding.json')]:
            copied = snapshot_root / item
            if not copied.exists():
                copied.parent.mkdir(parents=True, exist_ok=True)
                os.link(results / item, copied)
            snapshot_hashes[item.as_posix()] = sha(copied)
        primary_keys.append({**key, 'result_file': str((snapshot_root / relative).resolve())})
        snapshot_rows.append({'review_id': key['review_id'], 'original_result_file': key['result_file'],
            'result_sha256': key['result_sha256'], 'protocol_sha256': sha(results / cid / 'protocol.json')})
    save(primary_pack / 'evaluation_only/blind-key.json', primary_keys)
    primary_receipt = json.loads((primary_pack / 'pack-receipt.json').read_text('utf-8'))
    primary_receipt['blind_key_sha256'] = sha(primary_pack / 'evaluation_only/blind-key.json')
    save(primary_pack / 'pack-receipt.json', primary_receipt)
    snapshot_path = snapshot_parent / 'source-snapshot.json'
    save(snapshot_path, {'schema': 'source_reviewed_generation_snapshot_v1',
        'citation_pack_receipt_sha256': sha(citation_pack / 'receipt.json'),
        'citation_opinions_sha256': sha(citation_verdicts), 'plan_sha256': sha(plan_path),
        'selection_sha256': sha(selection_path), 'available_cases': len(keys),
        'pending_review_ids_at_citation_capture': [], 'gold_points_read': False,
        'automatic_scores_read': 0, 'model_requests': 0, 'rows': snapshot_rows,
        'file_sha256': snapshot_hashes})
    save(primary_pack / 'citation-release.json', {'schema': 'source_citation_before_primary_review_release_v1',
        'citation_pack_receipt_sha256': sha(citation_pack / 'receipt.json'),
        'citation_opinions_sha256': sha(citation_verdicts),
        'primary_pack_receipt_sha256': sha(primary_pack / 'pack-receipt.json'),
        'source_opinion_row_sha256': {r['review_id']: digest(r) for r in opinions},
        'available_cases': len(keys), 'pending_generation': 0, 'human_truth': False,
        'source_citation_gate_before_gold_read': True, 'model_requests': 0,
        'generation_snapshot_receipt_file': str(snapshot_path.resolve()),
        'generation_snapshot_receipt_sha256': sha(snapshot_path)})
    base = tmp_path / 'base'
    prepare_base(plan_path, evaluation, base, PROJECT, runtime)
    package = tmp_path / 'full_package'
    prepare(base, policy, package)
    args = SimpleNamespace(plan=plan_path, evaluation=evaluation, activation=activation, resources=resources,
        dataset=dataset, results=results, output=scores, review_selection=selection_path,
        review_pack=primary_pack, review_verdicts=verdicts, citation_policy=policy,
        citation_pack=citation_pack, citation_verdicts=citation_verdicts)
    return args, package, selection


def test_full1248_unknown_opinions_release_without_claiming_correctness(full_cohort):
    args, package, selection = full_cohort
    assert len(selection['cases']) == 1248
    reviews, _, rows, receipt = verify_complete_release(args)
    assert len(reviews) == len(rows) == receipt['registered_cases'] == 1248
    assert all(value is None for value in reviews.values())
    assert receipt['all_planned_citation_opinions'] == 1248
    assert receipt['verified_snapshot_cases'] == 1248
    assert receipt['automatic_score_files_read'] == receipt['network_requests'] == 0
    assert len(list((args.output / 'full-review-releases').glob('*.json'))) == 1
    assert not list(args.output.rglob('score.json'))
    manifest = json.loads((package / 'manifest.json').read_text('utf-8'))
    assert manifest['grading_mode'] == FULL_MODE
    for name, changes in manifest['full_review_control_flow_changes'].items():
        altered = (package / name).read_text('utf-8')
        for change in reversed(changes):
            altered = altered.replace(change['after'], change['before'])
        assert transform(altered, [(c['before'], c['after']) for c in changes]) == (package / name).read_text('utf-8')


def test_partial_missing_drift_and_early_selected_scores_all_rejected(full_cohort):
    args, _, selection = full_cohort
    def reject_file(path, mutation, message):
        original = path.read_bytes()
        value = json.loads(original)
        mutation(value)
        save(path, value)
        try:
            with pytest.raises(ValueError, match=message):
                verify_complete_release(args)
        finally:
            path.write_bytes(original)
        assert not (args.output / 'full-review-releases').exists()
    reject_file(args.review_pack / 'pack-receipt.json', lambda v: v.update(available_cases=294), 'full prospective')
    reject_file(args.citation_pack / 'receipt.json', lambda v: v.update(pending_review_ids=['pending']), 'full prospective')
    reject_file(args.review_verdicts, lambda v: v['rows'].pop(), 'complete available')
    reject_file(args.citation_verdicts, lambda v: v['rows'].pop(), 'every prospective citation')
    reject_file(args.citation_verdicts, lambda v: v.update(before_automatic_scores=False), 'source-first')
    reject_file(args.review_verdicts, lambda v: v.update(human_truth=True), 'human truth')
    reject_file(args.citation_pack / 'receipt.json', lambda v: v.update(declared_primary_scores_root='another-root'), 'another score root')
    key_path = args.review_pack / 'evaluation_only/blind-key.json'
    receipt_path = args.review_pack / 'pack-receipt.json'
    key_original, receipt_original = key_path.read_bytes(), receipt_path.read_bytes()
    changed = json.loads(key_original)
    changed[0]['result_file'] = 'wrong-result.json'
    save(key_path, changed)
    receipt = json.loads(receipt_original); receipt['blind_key_sha256'] = sha(key_path); save(receipt_path, receipt)
    with pytest.raises(ValueError, match='provenance drift|current original answer'):
        verify_complete_release(args)
    key_path.write_bytes(key_original); receipt_path.write_bytes(receipt_original)
    input_path = args.citation_pack / 'evaluation_only/inputs.json'
    receipt_path = args.citation_pack / 'receipt.json'
    input_original, receipt_original = input_path.read_bytes(), receipt_path.read_bytes()
    changed = json.loads(input_original); changed[0]['candidate_answer'] = 'Different answer.'; save(input_path, changed)
    receipt = json.loads(receipt_original); receipt['inputs_sha256'] = sha(input_path); save(receipt_path, receipt)
    with pytest.raises(ValueError, match='provenance drift|actual delivered'):
        verify_complete_release(args)
    input_path.write_bytes(input_original); receipt_path.write_bytes(receipt_original)
    row = selection['cases'][0]
    score = args.output / row['cell_id'] / 'sessions' / row['question_id'] / 'score.json'
    save(score, 'AUTOMATIC_LABEL_MUST_NOT_BE_READ')
    with pytest.raises(ValueError, match='precede their exact global'):
        verify_complete_release(args)
    assert score.read_text('utf-8') == json.dumps('AUTOMATIC_LABEL_MUST_NOT_BE_READ', ensure_ascii=False, indent=2) + '\n'


def test_real_worker_blocks_partial_then_preserves_fixed_request_bytes(full_cohort, monkeypatch):
    args, package, _ = full_cohort
    import chapter2_score_knowledge_formal as original
    for name, file in [('guard', 'guard.py'), ('full_review', 'full_review.py')]:
        spec = importlib.util.spec_from_file_location(name, package / file)
        module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
        monkeypatch.setitem(sys.modules, name, module)
    spec = importlib.util.spec_from_file_location('released_grader', package / 'grading.py')
    worker = importlib.util.module_from_spec(spec); spec.loader.exec_module(worker)
    calls, credentials = [], []
    class Client:
        def __init__(self, *unused): pass
        def __call__(self, body, index):
            calls.append(copy.deepcopy(body))
            value = json.loads(body['messages'][1]['content'])
            answer = ({'verdict': 'full', 'answer_segment_ids': [s['id'] for s in value['premise_segments']], 'reason': 'Conveys claim'}
                if 'hypothesis' in value else {'segments': [{'id': s['id'], 'verdict': 'supported', 'reason': 'Original support'}
                for s in value['candidate_segments']], 'condition': {'verdict': 'not_applicable', 'reason': 'None'}})
            return {'status': 'response', 'response': {'model': body['model'], 'usage': {'prompt_tokens': 100, 'completion_tokens': 100},
                'choices': [{'finish_reason': 'stop', 'message': {'content': json.dumps(answer)}}]}}
    def settings(_):
        credentials.append(True)
        return 'https://registered', 'not-a-real-key'
    for module in [original, worker]:
        monkeypatch.setattr(module, 'settings', settings)
        monkeypatch.setattr(module, 'load_tokenizer', lambda *unused: (lambda _: 100, {'model': 'qwen3-14b'}))
        monkeypatch.setattr(module, 'RecordedQwenClient', Client)
    argv = ['grader']
    for name, value in vars(args).items():
        argv += ['--' + name.replace('_', '-'), str(value)]
    argv += ['--cell', 'main/qwen3-14b_none/r01', '--proxy-settings', 'not-read']
    receipt_path = args.review_pack / 'pack-receipt.json'; protected = receipt_path.read_bytes()
    partial = json.loads(protected); partial['available_cases'] = 294; save(receipt_path, partial)
    monkeypatch.setattr(sys, 'argv', argv)
    with pytest.raises(ValueError, match='full prospective'):
        worker.main()
    assert calls == credentials == []
    assert not args.output.exists()
    receipt_path.write_bytes(protected)
    worker.main()
    released_requests = copy.deepcopy(calls)
    assert len(released_requests) == 32
    score_hashes = {p: sha(p) for p in args.output.rglob('score.json')}
    assert len(score_hashes) == 16
    calls.clear(); worker.main(); assert calls == []
    for p, value in score_hashes.items(): assert sha(p) == value
    # Original frozen scorer on the exact same full opinions is the byte baseline.
    baseline_argv = argv.copy()
    for name in ['citation-policy', 'citation-pack', 'citation-verdicts']:
        index = baseline_argv.index('--' + name); del baseline_argv[index:index + 2]
    baseline_argv[baseline_argv.index('--output') + 1] = str(args.output.parent / 'baseline')
    monkeypatch.setattr(sys, 'argv', baseline_argv); original.main()
    assert calls == released_requests
    assert len(list(args.output.rglob('full-review-releases/*.json'))) == 1


def test_snapshot_provenance_and_bytes_cannot_be_replaced_by_live_paths(full_cohort):
    args, _, selection = full_cohort
    release_path = args.review_pack / 'citation-release.json'
    release_original = release_path.read_bytes()
    release = json.loads(release_original)
    snapshot_path = Path(release['generation_snapshot_receipt_file'])
    snapshot_original = snapshot_path.read_bytes()
    for mutate, message in [
        (lambda v: v['rows'][0].update(original_result_file='another-original.json'), 'current original answer'),
        (lambda v: v['file_sha256'].pop(next(iter(v['file_sha256']))), 'file cohort drift'),
        (lambda v: v.update(automatic_scores_read=1), 'snapshot scope drift')]:
        value = json.loads(snapshot_original); mutate(value); save(snapshot_path, value)
        updated = json.loads(release_original); updated['generation_snapshot_receipt_sha256'] = sha(snapshot_path)
        save(release_path, updated)
        with pytest.raises(ValueError, match=message): verify_complete_release(args)
        snapshot_path.write_bytes(snapshot_original); release_path.write_bytes(release_original)
        assert not args.output.exists()
    key_path = args.review_pack / 'evaluation_only/blind-key.json'
    receipt_path = args.review_pack / 'pack-receipt.json'
    key_original, receipt_original = key_path.read_bytes(), receipt_path.read_bytes()
    keys = json.loads(key_original); case = selection['cases'][0]
    keys[0]['result_file'] = str(args.results / case['cell_id'] / 'sessions' / case['question_id'] / 'result.json')
    save(key_path, keys)
    receipt = json.loads(receipt_original); receipt['blind_key_sha256'] = sha(key_path); save(receipt_path, receipt)
    updated = json.loads(release_original); updated['primary_pack_receipt_sha256'] = sha(receipt_path); save(release_path, updated)
    with pytest.raises(ValueError, match='snapshot does not bind'): verify_complete_release(args)
    key_path.write_bytes(key_original); receipt_path.write_bytes(receipt_original); release_path.write_bytes(release_original)
    assert verify_complete_release(args, persist=False)[3]['verified_snapshot_cases'] == 1248
