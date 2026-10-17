"""Preserve unknown scores when malformed Unicode prevents a valid judge input."""
POLICY = 'unpaired_surrogate_input_unknown_v1'


def contains_surrogate(value):
    if isinstance(value, str):
        return any(0xD800 <= ord(character) <= 0xDFFF for character in value)
    if isinstance(value, dict):
        return any(contains_surrogate(k) or contains_surrogate(v) for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return any(contains_surrogate(v) for v in value)
    return False


def wrap(original):
    def score(result, payload, client, counter):
        if result['status'] == 'answered' and contains_surrogate(payload):
            return dict(status='judge_unknown', reason='unpaired_surrogate_input',
                        counted_input_tokens=0, physical_model_calls=0,
                        input_admission_policy=POLICY, content_repair=False,
                        metrics=dict(complete_valid_answer=None, complete_lower=0, complete_upper=1))
        return original(result, payload, client, counter)
    return score
