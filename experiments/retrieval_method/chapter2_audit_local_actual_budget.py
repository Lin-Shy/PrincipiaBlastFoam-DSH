"""Audit all fixed masked development answers against local context, without API calls."""
import argparse
import hashlib
import json
import sys
from pathlib import Path
from chapter2_qwen_local import LocalModel, prepare_body
from chapter2_qwen_compact_grammar import compact_grammar_requests


def read(p):
    return json.loads(p.read_text(encoding='utf-8'))


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def bodysha(body):
    return hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--activity', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    root = args.activity.resolve()
    prep_path = root/'development/local_actual_answer_audit_004/preparation.json'
    prep = read(prep_path)
    for name, value in prep['inputs_sha256'].items():
        if sha(root/name) != value:
            raise ValueError('Fixed masked input drift: ' + name)
    if prep['planned_answers'] != 15 or prep['selection_changed'] is not False:
        raise ValueError('All original fifteen answers required')
    registration_path = root/'development/local_score_calibration_004/registration.json'
    registration = read(registration_path)
    deployment = LocalModel(registration['endpoint'], registration['model'], 'not-loaded')
    budget_path = root/'setup/local_uniform_judge_004/input-budget.json'
    formal_budget = read(budget_path)
    for field, name in [('response_schema_implementation_sha256', 'chapter2_qwen_structured_output.py'),
                        ('hard_template_implementation_sha256', 'chapter2_qwen_hard_nonthinking.py'),
                        ('compact_grammar_implementation_sha256', 'chapter2_qwen_compact_grammar.py')]:
        if formal_budget[field] != sha(Path(__file__).with_name(name)):
            raise ValueError('Request transformation differs from validated full budget')
    resources_path = root/'development/formal_preparation_005/local-resources.json'
    tokenizer_dir = Path(read(resources_path)['tokenizer_qwen3-14b'])
    for name, value in read(tokenizer_dir/'artifact-binding.json')['files'].items():
        if sha(tokenizer_dir/name) != value:
            raise ValueError('Frozen tokenizer drift')
    from transformers import AutoTokenizer
    tokenizer = AutoTokenizer.from_pretrained(str(tokenizer_dir), local_files_only=True)
    old = root/'development/actual_answer_scoring_001'
    protocol = read(old/'protocol.json')
    for name, value in protocol['source_sha256'].items():
        if sha(old/'runtime'/name) != value:
            raise ValueError('Original input generator drift')
    sys.path.insert(0, str(old/'runtime/src'))
    sys.path.insert(0, str(old/'runtime/experiments/retrieval_method'))
    from chapter2_partial_answer_scoring import source_free_requests
    masked = {r['question_id']:r for r in read(root/'development/actual_answer_review_001/evaluation_only/inputs.json')}
    by_question = {read(p)['question_id']: p.parent for p in old.glob('sessions/*/score.json')}
    rows = []
    for item in prep['rows']:
        files = sorted((by_question[item['question_id']]/'requests').glob('*.json'))
        source = masked[item['question_id']]
        payload = {k:source[k] for k in ('question','answer','rubric','original_material')}
        logical = source_free_requests(payload) if item['generation_status']=='answered' else []
        if [r['body'] for r in logical] != [read(p)['request'] for p in files]:
            raise ValueError('Original request reconstruction drift')
        requests = compact_grammar_requests(logical)
        actual = [prepare_body(r['body'], deployment) for r in requests]
        hashes = [bodysha(body) for body in actual]
        if hashes != item['actual_request_sha256'] or len(actual) != item['planned_requests']:
            raise ValueError('Prepared actual request drift')
        counts = [len(tokenizer.apply_chat_template(body['messages'], tokenize=True,
                  add_generation_prompt=True, enable_thinking=False)) for body in actual]
        rows.append(dict(review_id=item['review_id'], question_id=item['question_id'],
                         actual_request_sha256=hashes, actual_input_tokens=counts,
                         local_context_exceeded=any(n+4096 > formal_budget['local_context_limit'] for n in counts)))
    report = dict(schema='compact_local_actual_development_budget_v1', answers=len(rows),
                  planned_requests=sum(len(r['actual_input_tokens']) for r in rows), rows=rows,
                  local_context_limit=formal_budget['local_context_limit'], fixed_output_cap=4096,
                  max_input_tokens=max(n for r in rows for n in r['actual_input_tokens']),
                  context_exceeding_answers=sum(r['local_context_exceeded'] for r in rows),
                  answers_truncated=False, model_calls=0, credentials_loaded=False, method_key_decoded=False,
                  formal_activation=False, semantic_acceptance=False,
                  inputs_sha256={str(p):sha(p) for p in [prep_path,registration_path,budget_path,
                    resources_path,tokenizer_dir/'artifact-binding.json',Path(__file__)]})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(json.dumps({k:report[k] for k in ['answers','planned_requests','max_input_tokens',
                                          'context_exceeding_answers','model_calls']}))


if __name__ == '__main__':
    main()
