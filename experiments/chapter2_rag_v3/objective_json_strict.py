"""Reject duplicate JSON fields before scoring an answer (post-pilot audit)."""
import json
from objective_json_pilot import score as pilot_score


def unique_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError('duplicate JSON field')
        obj[key] = value
    return obj


def score(question, gold, result):
    if result and result.get('status') == 'answered':
        try:
            turn = result['turns'][-1]
            text = turn['response']['response']['choices'][0]['message']['content']
            parsed = json.loads(text, object_pairs_hook=unique_object)
            if parsed != turn['action']:
                raise ValueError('action differs from raw JSON')
        except (ValueError, KeyError, IndexError, TypeError):
            return dict(id=question['id'], type=question['type'], raw_answer=result.get('answer') or '',
                        normalized_answer='', score=0, format_valid=False,
                        reason='invalid_or_duplicate_json', scoring_version='json_answer_strict_v2')
    row = pilot_score(question, gold, result)
    row['scoring_version'] = 'json_answer_strict_v2'
    return row
