"""全部预选引用及主回答意见齐备后，才释放原固定评分器。"""
import hashlib
import json
from pathlib import Path


def read(path):
    return json.loads(Path(path).read_text('utf-8'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def complete_pack(pack, receipt_name, schema, selection, setup, plan_hash):
    receipt = read(pack / receipt_name)
    expected = {r['review_id'] for r in selection['cases']}
    if (receipt.get('schema') != schema or receipt.get('plan_sha256') != plan_hash
            or receipt.get('selection_sha256') != setup['review_selection_sha256']
            or receipt.get('planned_cases') != len(expected)
            or receipt.get('available_cases') != len(expected)
            or receipt.get('pending_review_ids') != []
            or receipt.get('automatic_scores_read') != 0):
        raise ValueError('full prospective review pack required; partial cohorts cannot release scores')
    if receipt['inputs_sha256'] != sha(pack / 'evaluation_only/inputs.json') or receipt[
            'blind_key_sha256'] != sha(pack / 'evaluation_only/blind-key.json'):
        raise ValueError('full review pack byte binding drift')
    inputs = read(pack / 'evaluation_only/inputs.json')
    keys = read(pack / 'evaluation_only/blind-key.json')
    for rows in [inputs, keys]:
        ids = [r['review_id'] for r in rows]
        if len(ids) != len(expected) or set(ids) != expected:
            raise ValueError('full review cohort missing or duplicated')
    return receipt, {r['review_id']: r for r in inputs}, {r['review_id']: r for r in keys}


def verify_complete_release(args, selection=None, setup=None, loader=None, *, persist=True):
    """控制执行顺序，不改写或替代原意见、评分和未知边界。

    No credentials, HTTP clients or automatic score files are read here.
    Unknown source opinions are completed opinions, not invented positive labels.
    The same checks run in the controller and in every direct grading worker.
    """
    for name in ('review_pack', 'review_verdicts', 'citation_policy', 'citation_pack', 'citation_verdicts'):
        if getattr(args, name, None) is None:
            raise ValueError('full primary and citation review artifacts required')
    from chapter2_knowledge_evaluation import verify_setup, verify_dataset, bound_result, delivered_lines
    from chapter2_knowledge_formal_plan import validate_activation, activation_identity
    from chapter2_knowledge_formal_review import verify_selection, masked_item
    from chapter2_analyze_knowledge_formal import load_independent_review
    from chapter2_answer_scoring import scoring_payload
    from chapter2_citation_original_review import masked_case, validate_review
    from principia_core.retrieval.knowledge_qa import FrozenKnowledgeCorpus
    setup = read(args.evaluation) if setup is None else setup
    plan = verify_setup(setup, args.plan)
    plan_hash = sha(args.plan)
    selection = read(args.review_selection) if selection is None else selection
    selection = verify_selection(selection, plan, plan_hash)
    if sha(args.review_selection) != setup['review_selection_sha256']:
        raise ValueError('full release selection differs from accepted evaluation')
    expected = {(r['cell_id'], r['question_id']) for r in selection['cases']}
    primary_receipt, primary_inputs, primary_keys = complete_pack(
        args.review_pack, 'pack-receipt.json', 'formal_method_masked_original_review_pack_v1',
        selection, setup, plan_hash)
    citation_receipt, citation_inputs, citation_keys = complete_pack(
        args.citation_pack, 'receipt.json', 'masked_citation_original_review_pack_v1',
        selection, setup, plan_hash)
    policy = read(args.citation_policy)
    package_manifest = Path(__file__).with_name('manifest.json')
    if package_manifest.exists() and sha(args.citation_policy) != read(package_manifest)[
            'full_review_citation_policy_sha256']:
        raise ValueError('full release citation policy differs from execution registration')
    if (policy.get('schema') != 'prospective_citation_original_review_policy_v1'
            or policy.get('plan_sha256') != plan_hash
            or policy.get('selection_sha256') != setup['review_selection_sha256']
            or policy.get('planned_cases') != len(expected)
            or policy.get('primary_judge_changed') is not False
            or policy.get('failed_automatic_citation_judge_adopted') is not False
            or citation_receipt.get('policy_sha256') != sha(args.citation_policy)
            or citation_receipt.get('gold_points_read') is not False
            or citation_receipt.get('formal_result') is not True):
        raise ValueError('full release citation policy or gold-free scope drift')
    if Path(citation_receipt['declared_primary_scores_root']).resolve() != args.output.resolve():
        raise ValueError('full citation review was prepared against another score root')
    # Verify the actual validators against the registered source policy.
    import chapter2_citation_original_review as citation_module
    import chapter2_citation_support as citation_support
    for module in [citation_module, citation_support]:
        relative = 'experiments/retrieval_method/' + module.__name__ + '.py'
        if sha(module.__file__) != policy['runtime_source_sha256'][relative]:
            raise ValueError('full release citation validator differs from frozen policy')
    loader = load_independent_review if loader is None else loader
    reviews, bindings, rows = loader(args.review_pack, args.review_verdicts, selection, setup, with_rows=True)
    if set(reviews) != expected or set(bindings) != expected or set(rows) != expected:
        raise ValueError('every prospective primary opinion must precede selected grading')
    citation_value = read(args.citation_verdicts)
    citation_review = validate_review(citation_value, list(citation_inputs.values()))
    if set(citation_review) != {r['review_id'] for r in selection['cases']}:
        raise ValueError('every prospective citation opinion must precede selected grading')
    try:
        from full_snapshot import verify_primary_snapshot
    except ModuleNotFoundError:
        from chapter2_full_review_snapshot_binding import verify_primary_snapshot
    snapshot_proof = verify_primary_snapshot(args, selection, primary_receipt, citation_receipt,
                                             citation_value, primary_keys)
    if not snapshot_proof['full_registered_snapshot_complete']:
        raise ValueError('partial snapshot metadata validation cannot release selected scores')
    activation = read(args.activation)
    validate_activation(activation, plan, plan_hash)
    if citation_receipt.get('activation_sha256') != sha(args.activation):
        raise ValueError('citation pack belongs to another admission registry')
    verify_dataset(args.dataset, setup['dataset_seal_sha256'])
    resources = read(args.resources)
    if sha(resources['corpus_manifest']) != plan['artifacts_sha256']['corpus_manifest']:
        raise ValueError('full review authoritative corpus manifest drift')
    corpus = FrozenKnowledgeCorpus(Path(resources['corpus']), Path(resources['corpus_manifest']))
    questions = {r['id']: r for r in read(args.dataset / 'model/questions.json')}
    annotations = {r['id']: r for r in read(args.dataset / 'scoring/annotations.json')}
    evidence = read(args.dataset / 'scoring/evidence.json')
    cells = {c['id']: c for c in plan['cells']}
    for row in selection['cases']:
        rid, cell_id, qid = row['review_id'], row['cell_id'], row['question_id']
        admission = activation_identity(activation, sha(args.activation), cell_id)
        observation = bound_result(args.results, cells[cell_id], questions[qid], plan_hash, admission)
        if observation is None:
            raise ValueError('full review case lacks its original bound answer')
        path, result = observation
        result_hash = sha(path)
        for key in [primary_keys[rid], citation_keys[rid]]:
            if (key.get('cell_id') != cell_id or key.get('question_id') != qid
                    or key.get('result_sha256') != result_hash):
                raise ValueError('full review key does not bind the current original answer')
        if Path(citation_keys[rid]['result_file']).resolve() != path.resolve():
            raise ValueError('full citation key does not bind the current original answer')
        if bindings[(cell_id, qid)] != result_hash:
            raise ValueError('full primary opinion binds a different answer')
        payload = scoring_payload(questions[qid]['question'], annotations[qid], evidence,
            corpus, result['answer'], delivered_lines(result)) if result['status'] == 'answered' else None
        if primary_inputs[rid] != masked_item(rid, result, payload):
            raise ValueError('full primary material does not match original frozen answer and sources')
        if citation_inputs[rid] != masked_case(rid, questions[qid]['question'], result, corpus):
            raise ValueError('full citation material does not match actual delivered cited originals')
    files = {'plan': args.plan, 'evaluation': args.evaluation, 'activation': args.activation,
             'selection': args.review_selection, 'primary_pack_receipt': args.review_pack / 'pack-receipt.json',
             'primary_verdicts': args.review_verdicts, 'citation_policy': args.citation_policy,
             'citation_pack_receipt': args.citation_pack / 'receipt.json', 'citation_verdicts': args.citation_verdicts}
    receipt = {'schema': 'global_preselected_source_first_release_v1', **snapshot_proof,
        'all_planned_primary_opinions': len(reviews), 'all_planned_citation_opinions': len(citation_review),
        'registered_cases': len(expected), 'input_sha256': {k: sha(p) for k, p in files.items()},
        'primary_inputs_sha256': primary_receipt['inputs_sha256'],
        'primary_key_sha256': primary_receipt['blind_key_sha256'],
        'citation_inputs_sha256': citation_receipt['inputs_sha256'],
        'citation_key_sha256': citation_receipt['blind_key_sha256'],
        'helper_sha256': sha(Path(__file__)), 'automatic_score_files_read': 0,
        'credentials_loaded': False, 'network_requests': 0,
        'ai_opinions_not_human_truth': True, 'unknown_opinions_permitted': True,
        'fixed_v7_and_source_opinions_unchanged': True}
    if package_manifest.exists():
        receipt['execution_package_manifest_sha256'] = sha(package_manifest)
    raw = (json.dumps(receipt, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    target = args.output / 'full-review-releases' / (hashlib.sha256(raw).hexdigest() + '.json')
    if any((args.output / cell_id / 'sessions' / qid / 'score.json').exists()
           for cell_id, qid in expected):
        if not target.exists() or target.read_bytes() != raw:
            raise ValueError('selected scores cannot precede their exact global source-first release')
    if persist:
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if target.read_bytes() != raw:
                raise ValueError('immutable full review release receipt drift')
        else:
            with target.open('xb') as stream:
                stream.write(raw)
    return reviews, bindings, rows, receipt


def load_complete_independent_review(args, selection, setup, loader):
    return verify_complete_release(args, selection, setup, loader)[:3]
