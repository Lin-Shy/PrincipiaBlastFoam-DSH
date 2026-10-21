"""Source-first citation opinions with verbatim support, never an API judge.

Gold points and correctness grades are absent. This is a fallible Codex source
review of the prospectively selected cohort, not an automatic full-test metric
or human truth. Each affirmative support link binds actual cited original lines.
"""
from chapter2_citation_support import citation_payload


def masked_case(review_id, question, result, corpus):
    payload, admission = citation_payload(question, result, corpus)
    return {'review_id': review_id, 'question': question,
            'candidate_answer': result.get('answer') if result.get('status') == 'answered' else None,
            'admission': admission, 'candidate_segments': payload['candidate_segments'] if payload else [],
            'cited_originals': payload['cited_originals'] if payload else []}


def deterministic_metrics(case):
    status = case['admission']['status']
    if status == 'ready': return None
    if status not in {'generation_failed', 'no_citations', 'invalid_references', 'undelivered_references'}:
        raise ValueError('unrecognized citation admission')
    return {'complete_citation_support': 0, 'complete_lower': 0, 'complete_upper': 0,
            'segment_support_lower': 0, 'segment_support_upper': 1,
            'reference_usefulness_lower': 0, 'reference_usefulness_upper': 1,
            'semantic_review_required': False, 'status': status}


def validate_opinion(opinion, case):
    """Verify IDs and source quotes; do not pretend these checks prove entailment."""
    if set(opinion) != {'review_id', 'segments', 'references'} or opinion['review_id'] != case['review_id']:
        raise ValueError('citation opinion belongs to another masked case')
    if deterministic_metrics(case) is not None:
        if opinion['segments'] or opinion['references']: raise ValueError('nonadmitted citation case cannot receive semantic labels')
        return deterministic_metrics(case)
    segments = {r['id']: r for r in case['candidate_segments']}
    originals = {r['id']: r for r in case['cited_originals']}
    def rows(values, expected):
        if not isinstance(values, list) or any(not isinstance(r, dict) for r in values): raise ValueError('citation rows invalid')
        ids = [r.get('id') for r in values]
        if any(not isinstance(v, str) for v in ids) or len(ids) != len(set(ids)) or set(ids) != set(expected):
            raise ValueError('citation opinion IDs missing, duplicated or invented')
    rows(opinion['segments'], segments); rows(opinion['references'], originals)
    positive_links = {rid: set() for rid in originals}
    for row in opinion['segments']:
        if (set(row) != {'id', 'verdict', 'support', 'reason'} or row['verdict'] not in
                {'supported', 'partial', 'not_supported', 'contradicted', 'unknown', 'not_substantive'}
                or not isinstance(row['reason'], str) or not row['reason'].strip()
                or not isinstance(row['support'], list)):
            raise ValueError('citation segment opinion invalid')
        if row['verdict'] in {'supported', 'partial', 'contradicted'} and not row['support']:
            raise ValueError('affirmative support/contradiction needs original quotes')
        if row['verdict'] == 'not_substantive' and row['support']: raise ValueError('nonclaim must not manufacture support')
        seen_quotes = set()
        for support in row['support']:
            if (set(support) != {'reference_id', 'line_start', 'line_end', 'quote'}
                    or support['reference_id'] not in originals
                    or type(support['line_start']) is not int or type(support['line_end']) is not int):
                raise ValueError('citation original support coordinate invalid')
            raw = originals[support['reference_id']]; start = support['line_start']; end = support['line_end']
            if not raw['start'] <= start <= end <= raw['end']: raise ValueError('support quote outside actually cited span')
            quote = '\n'.join(r['text'] for r in raw['lines'] if start <= r['number'] <= end)
            if support['quote'] != quote or not quote.strip(): raise ValueError('support quote not verbatim cited original')
            key = (support['reference_id'], start, end)
            if key in seen_quotes: raise ValueError('duplicate original quote')
            seen_quotes.add(key)
            if row['verdict'] in {'supported', 'partial'}: positive_links[support['reference_id']].add(row['id'])
    for row in opinion['references']:
        if (set(row) != {'id', 'verdict', 'segment_ids', 'reason'} or row['verdict'] not in {'useful', 'unused', 'unknown'}
                or not isinstance(row['reason'], str) or not row['reason'].strip()
                or not isinstance(row['segment_ids'], list) or any(not isinstance(s, str) for s in row['segment_ids'])
                or len(row['segment_ids']) != len(set(row['segment_ids'])) or not set(row['segment_ids']) <= set(segments)):
            raise ValueError('citation reference opinion invalid')
        links = positive_links[row['id']]
        if row['verdict'] == 'useful' and (not links or set(row['segment_ids']) != links):
            raise ValueError('useful reference must match all actual positive support links')
        if row['verdict'] == 'unused' and (links or row['segment_ids']): raise ValueError('unused reference contradicts positive support')
        if row['verdict'] == 'unknown' and row['segment_ids']: raise ValueError('unknown reference cannot assert a support link')
    substantive = [r for r in opinion['segments'] if r['verdict'] != 'not_substantive']
    n = len(substantive); nr = len(originals)
    good = sum(r['verdict'] == 'supported' for r in substantive); u = sum(r['verdict'] == 'unknown' for r in substantive)
    useful = sum(r['verdict'] == 'useful' for r in opinion['references']); ur = sum(r['verdict'] == 'unknown' for r in opinion['references'])
    failed = not n or any(r['verdict'] in {'partial', 'not_supported', 'contradicted'} for r in substantive) or any(
        r['verdict'] == 'unused' for r in opinion['references'])
    complete = 0 if failed else None if u or ur else 1
    return {'complete_citation_support': complete, 'complete_lower': int(complete == 1), 'complete_upper': int(complete != 0),
            'segment_support_lower': good / n if n else 0, 'segment_support_upper': (good + u) / n if n else 0,
            'reference_usefulness_lower': useful / nr, 'reference_usefulness_upper': (useful + ur) / nr,
            'substantive_segments': n, 'unknown_segments': u, 'unique_references': nr, 'unknown_references': ur,
            'semantic_review_required': True, 'status': 'source_reviewed_ai_opinion'}


def validate_review(value, cases):
    if set(value) != {'schema', 'reviewer', 'human_truth', 'before_automatic_scores', 'gold_points_read', 'rows'}:
        raise ValueError('strict citation original-review record required')
    if (value['schema'] != 'source_first_citation_original_review_v1' or value['reviewer'] != 'Codex (AI)'
            or value['human_truth'] is not False or value['before_automatic_scores'] is not True or value['gold_points_read'] is not False):
        raise ValueError('citation opinions require honest AI identity and source-first/gold-free scope')
    rows = value['rows']
    if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows): raise ValueError('citation reviews invalid')
    ids = [r.get('review_id') for r in rows]
    expected = {r['review_id']: r for r in cases}
    if len(ids) != len(set(ids)) or any(not isinstance(v, str) for v in ids) or not set(ids) <= set(expected):
        raise ValueError('citation review case unknown or duplicate')
    # Partial progress is allowed; missing opinions remain unknown in the
    # entire predetermined cohort. Never manufacture complete denominators.
    return {r['review_id']: validate_opinion(r, expected[r['review_id']]) for r in rows}
