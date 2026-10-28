"""Offline request/response adapters. This revision intentionally has NO network transport.

Request building is not evidence that a provider accepts the request. A separately
approved, metered transport must be reviewed before any future live execution.
"""
import argparse
import hashlib
import json
from pathlib import Path
from judge_contract import VERSION, validate


def canonical(x):
    return json.dumps(x, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def digest(x):
    return hashlib.sha256(canonical(x)).hexdigest()


def build(profile, packet, phase, prompt, schema):
    if profile['judge_id'] not in ['gpt_astra', 'deepseek', 'qwen3_14b', 'gpt_sol', 'deepseek_flash']:
        raise ValueError('Not an API judge')
    if phase not in ['coverage', 'evidence', 'joint'] or packet['schema_version'] != VERSION:
        raise ValueError('Wrong phase/contract')
    allowed = {'schema_version', 'sample_id', 'question', 'answer', 'generation_failed', 'criteria'} if phase == 'coverage' else {
        'schema_version', 'sample_id', 'question', 'answer', 'generation_failed', 'conditional', 'sources'}
    if phase == 'joint':
        allowed.add('criteria')
    if set(packet) - allowed:
        raise ValueError('Packet has unapproved fields; no identities, other grades or cross-phase data')
    if phase in ('coverage', 'joint') and 'criteria' not in packet or phase in ('evidence', 'joint') and 'sources' not in packet:
        raise ValueError('Incomplete phase packet')
    # JSON schema is supplied as task text. No unverified server-side schema flag.
    instructions = prompt + '\nReturn exactly one JSON object. Required identity: ' + json.dumps({
        'schema_version': VERSION, 'sample_id': packet['sample_id'],
        'judge_id': profile['judge_id'], 'judge_version': profile['prompt_version'], 'status': 'complete'})
    instructions += '\nOutput schema: ' + json.dumps(schema, ensure_ascii=False)
    content = json.dumps(packet, ensure_ascii=False)
    body = {'model': profile['model_id'], 'stream': profile.get('stream',False)}
    if profile['protocol'] == 'responses':
        body.update(input=[{'role': 'system', 'content': instructions}, {'role': 'user', 'content': content}],
                    max_output_tokens=profile['output_token_cap'], store=False)
    elif profile['protocol'] == 'chat_completions':
        body.update(messages=[{'role': 'system', 'content': instructions}, {'role': 'user', 'content': content}])
        body[profile.get('output_token_field','max_tokens')]=profile['output_token_cap']
        if body['stream']:body['stream_options']={'include_usage':True}
    else:
        raise ValueError('Unsupported protocol')
    body.update(profile['wire_parameters'])
    return {'url': profile['base_url'].rstrip('/') + ('/responses' if profile['protocol'] == 'responses' else '/chat/completions'),
            'body': body, 'authentication': {'scheme': 'Bearer', 'environment_variable': profile['key_env']},
            'request_sha256': digest(body), 'profile_sha256': digest(profile),
            'status': 'offline_draft_not_sent', 'capabilities_verified_live': False}


def usage(raw, protocol):
    u = raw.get('usage')
    if not isinstance(u, dict):
        raise ValueError('usage_unknown_stop_and_reconcile')
    ik, ok = ('input_tokens', 'output_tokens') if protocol == 'responses' else ('prompt_tokens', 'completion_tokens')
    i, o = u.get(ik), u.get(ok)
    if any(type(v) is not int or v < 0 for v in [i, o]):
        raise ValueError('usage_unknown_stop_and_reconcile')
    inp = u.get('input_tokens_details' if protocol == 'responses' else 'prompt_tokens_details') or {}
    out = u.get('output_tokens_details' if protocol == 'responses' else 'completion_tokens_details') or {}
    c = inp.get('cached_tokens', u.get('prompt_cache_hit_tokens'))
    r = out.get('reasoning_tokens')
    if c is not None and (type(c) is not int or not 0 <= c <= i):
        raise ValueError('Invalid cache accounting')
    if r is not None and (type(r) is not int or not 0 <= r <= o):
        raise ValueError('Invalid reasoning accounting')
    return dict(input_tokens=i, output_tokens=o, cached_input_tokens=c, reasoning_tokens=r,
                output_includes_reasoning=True, no_cache_discount_assumed=c is None)


def no_duplicates(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON field')
        result[key] = value
    return result


def parse(profile, raw, packet, phase):
    if raw.get('model') not in profile['allowed_response_model_ids']:
        raise ValueError('model_identity_mismatch')
    if profile['protocol'] == 'responses':
        if raw.get('status') != 'completed' or raw.get('error') or raw.get('incomplete_details'):
            raise ValueError('Incomplete/refused response')
        chunks = []
        for item in raw.get('output', []):
            if item.get('type') == 'reasoning':
                continue  # Preserve raw separately, never treat reasoning as final JSON.
            if item.get('type') != 'message' or item.get('role') != 'assistant':
                raise ValueError('Unexpected response item')
            for part in item.get('content', []):
                if part.get('type') != 'output_text':
                    raise ValueError('Refusal/nontext response')
                chunks.append(part['text'])
        content = ''.join(chunks)
    else:
        choices = raw.get('choices', [])
        if len(choices) != 1 or choices[0].get('finish_reason') != 'stop':
            raise ValueError('Truncated/multiple response')
        msg = choices[0]['message']
        if msg.get('refusal') or msg.get('tool_calls') or msg.get('function_call'):
            raise ValueError('Unexpected refusal/tool call')
        content = msg.get('content')
    if not isinstance(content, str):
        raise ValueError('No final text')
    record = json.loads(content, object_pairs_hook=no_duplicates)
    validate(record, phase, [c['criterion_id'] for c in packet['criteria']] if phase in ('coverage', 'joint') else None,
             packet.get('conditional') if phase in ('evidence', 'joint') else None)
    if record['sample_id'] != packet['sample_id'] or record['judge_id'] != profile['judge_id'] or record['judge_version'] != profile['prompt_version']:
        raise ValueError('Scoring identity mismatch')
    if phase in ('evidence', 'joint'):
        if packet['conditional'] and record['applicability_gate'] == 'not_applicable':
            raise ValueError('Conditional gate missing')
        if not packet['conditional'] and record['applicability_gate'] != 'not_applicable':
            raise ValueError('Nonconditional gate must be not_applicable')
    u = usage(raw, profile['protocol'])
    if u['input_tokens'] > profile['input_token_cap'] or u['output_tokens'] > profile['output_token_cap']:
        raise ValueError('Provider exceeds reservation; stop')
    return dict(record=record, usage=u, raw_response_sha256=digest(raw),
                response_id=raw.get('id'), response_model=raw['model'], system_fingerprint=raw.get('system_fingerprint'))


def execute(*args, **kwargs):
    raise PermissionError('This offline adapter has no live transport, key loader or retry path. Live execution requires the central scope and financial gates.')


def central_profile(judge_id, config_dir=None):
    """All NEW judge profiles resolve through the central registry, never old drafts."""
    import sys
    project = Path(__file__).resolve().parents[2]
    sys.path.insert(0, str(project / 'src'))
    from principia_core.config.llm import Registry
    return (Registry(config_dir) if config_dir else Registry()).judge_profile(judge_id)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--execute', action='store_true')
    p.add_argument('--profile', type=Path)
    p.add_argument('--judge', choices=['gpt_astra', 'deepseek', 'qwen3_14b', 'gpt_sol', 'deepseek_flash'])
    p.add_argument('--config-dir', type=Path)
    p.add_argument('--packet', type=Path)
    p.add_argument('--phase', choices=['coverage', 'evidence', 'joint'])
    p.add_argument('--prompt', type=Path)
    p.add_argument('--schema', type=Path)
    p.add_argument('--out', type=Path)
    a = p.parse_args()
    if a.execute:
        execute()
    if not all([a.judge, a.packet, a.phase, a.prompt, a.schema, a.out]) or a.profile:
        p.error('New dry preparation requires central --judge, packet, phase, prompt, schema and out; legacy --profile is no longer an execution entry')
    read = lambda path: json.loads(path.read_text(encoding='utf-8-sig'))
    result = build(central_profile(a.judge, a.config_dir), read(a.packet), a.phase, a.prompt.read_text(encoding='utf-8-sig'), read(a.schema))
    with a.out.open('x', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)


if __name__ == '__main__':
    main()
