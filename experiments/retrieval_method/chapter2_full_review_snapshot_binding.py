"""校验既有004引用先行释放与不可变来源快照，不要求把快照改成活目录。"""
import hashlib
import json
from pathlib import Path


def read(path):
    return json.loads(Path(path).read_text('utf-8'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def canonical(path):
    return str(Path(path).resolve()).removeprefix('\\\\?\\').casefold()


def verify_primary_snapshot(args, selection, primary_receipt, citation_receipt, citation_value, primary_keys):
    from chapter2_knowledge_formal_plan import digest
    release_path = args.review_pack / 'citation-release.json'
    release = read(release_path)
    source_rows = {r['review_id']: digest(r) for r in citation_value['rows']}
    # This metadata validator also audits captured partial snapshots; only
    # the caller's independent complete-pack gate authorizes any scoring.
    all_ids = {r['review_id'] for r in selection['cases']}
    ids = set(primary_keys)
    pending = primary_receipt['pending_review_ids']
    n = len(ids)
    if (not ids <= all_ids or len(pending) != len(set(pending))
            or ids & set(pending) or ids | set(pending) != all_ids):
        raise ValueError('primary snapshot must partition the entire prospective cohort')
    if (release.get('schema') != 'source_citation_before_primary_review_release_v1'
            or release.get('citation_pack_receipt_sha256') != sha(args.citation_pack / 'receipt.json')
            or release.get('citation_opinions_sha256') != sha(args.citation_verdicts)
            or release.get('primary_pack_receipt_sha256') != sha(args.review_pack / 'pack-receipt.json')
            or release.get('source_opinion_row_sha256') != source_rows
            or release.get('available_cases') != n or release.get('pending_generation') != len(pending)
            or release.get('source_citation_gate_before_gold_read') is not True
            or release.get('human_truth') is not False or release.get('model_requests') != 0):
        raise ValueError('full primary source-first release provenance drift')
    snapshot_path = Path(release['generation_snapshot_receipt_file'])
    if sha(snapshot_path) != release.get('generation_snapshot_receipt_sha256'):
        raise ValueError('full primary source snapshot receipt drift')
    snapshot = read(snapshot_path)
    if (snapshot.get('schema') != 'source_reviewed_generation_snapshot_v1'
            or snapshot.get('citation_pack_receipt_sha256') != sha(args.citation_pack / 'receipt.json')
            or snapshot.get('citation_opinions_sha256') != sha(args.citation_verdicts)
            or snapshot.get('plan_sha256') != sha(args.plan)
            or snapshot.get('selection_sha256') != sha(args.review_selection)
            or snapshot.get('available_cases') != n
            or snapshot.get('pending_review_ids_at_citation_capture') != pending
            or snapshot.get('gold_points_read') is not False
            or snapshot.get('automatic_scores_read') != 0 or snapshot.get('model_requests') != 0):
        raise ValueError('full primary immutable snapshot scope drift')
    rows = snapshot['rows']
    if len(rows) != n or {r['review_id'] for r in rows} != ids:
        raise ValueError('full primary snapshot cohort drift')
    rows = {r['review_id']: r for r in rows}
    root = snapshot_path.parent / 'results'
    expected_files = set()
    for case in selection['cases']:
        rid, cid, qid = case['review_id'], case['cell_id'], case['question_id']
        if rid not in ids:
            continue
        relative = Path(cid) / 'sessions' / qid / 'result.json'
        live = args.results / relative
        frozen = root / relative
        protocol = Path(cid) / 'protocol.json'
        expected_files.update([relative.as_posix(), relative.with_name('result-binding.json').as_posix(), protocol.as_posix()])
        row, key = rows[rid], primary_keys[rid]
        if (canonical(key['result_file']) != canonical(frozen)
                or canonical(row['original_result_file']) != canonical(live)
                or row['result_sha256'] != key['result_sha256']
                or sha(frozen) != sha(live) or sha(frozen) != row['result_sha256']
                or sha(root / protocol) != sha(args.results / protocol)
                or sha(root / protocol) != row['protocol_sha256']):
            raise ValueError('full primary snapshot does not bind the current original answer')
    if set(snapshot['file_sha256']) != expected_files:
        raise ValueError('full primary snapshot file cohort drift')
    for relative, expected in snapshot['file_sha256'].items():
        path = root / relative
        if not canonical(path).startswith(canonical(root) + '\\') and not path.resolve().is_relative_to(root.resolve()):
            raise ValueError('full primary snapshot path escapes declared root')
        if sha(path) != expected or sha(args.results / relative) != expected:
            raise ValueError('full primary snapshot file differs from original bound bytes')
    return {'citation_release_sha256': sha(release_path), 'generation_snapshot_receipt_sha256': sha(snapshot_path),
            'verified_snapshot_cases': n, 'verified_snapshot_files': len(expected_files),
            'full_registered_snapshot_complete': n == len(all_ids) and not pending,
            'snapshot_validation_is_not_a_partial_scoring_release': True}
