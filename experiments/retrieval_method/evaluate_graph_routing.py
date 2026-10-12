"""Freeze, run and score a single-step model router; labels never enter model messages."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

PROJECT = Path(__file__).resolve().parents[2]
ROOT = PROJECT.parent
SKILL = PROJECT / '.dsh/skills/blastfoam-knowledge'
DATASET = ROOT / 'dataset/retrieval/blastfoam_graph_routing_v1'
PROMPT = Path(__file__).parent / 'prompts/graph_router.md'


def read(path):
    return json.loads(path.read_text())


def lines(path):
    return [json.loads(x) for x in path.read_text().splitlines()]


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pilot_graph():
    sys.path.insert(0, str(SKILL / 'scripts'))
    spec = importlib.util.spec_from_file_location('graph_routing_pilot', SKILL / 'scripts/graph_query.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.PilotGraph(SKILL)


def messages(question, catalog, prompt):
    # Accept an already projected string; never serialize a dataset row here.
    if not isinstance(question, str):
        raise ValueError('question must be text, not an annotated row')
    return [{'role': 'system', 'content': prompt},
            {'role': 'user', 'content': json.dumps({'question': question, 'catalog': catalog}, ensure_ascii=False)}]


def prepare(output):
    protocol = read(DATASET / 'protocol.json')
    for name, expected in protocol['frozen_sha256'].items():
        assert sha(DATASET / name) == expected, name
    graph = pilot_graph()
    catalog = graph.catalog()
    prompt = PROMPT.read_text()
    questions = lines(DATASET / 'questions.jsonl')
    assert len(questions) == protocol['cases'] and len({q['id'] for q in questions}) == len(questions)
    assert all(set(q) == {'id', 'query'} for q in questions)
    output.mkdir(parents=True, exist_ok=False)
    write(output / 'inputs.json', [{'id': q['id'], 'messages': messages(q['query'], catalog, prompt)} for q in questions])
    write(output / 'catalog.json', catalog)
    frozen = [Path(__file__), PROMPT, DATASET / 'protocol.json', DATASET / 'questions.jsonl',
              DATASET / 'annotations.jsonl', SKILL / 'scripts/graph_query.py',
              SKILL / 'scripts/validate_semantic.py', SKILL / 'semantic/pilot/manifest.json',
              SKILL / 'semantic/pilot/facts.jsonl', SKILL / 'scripts/knowledge.py',
              SKILL / 'scripts/ranking.py', SKILL / 'references/terms.json', SKILL / 'index/current.json']
    write(output / 'frozen.json', {'files': {str(p.relative_to(ROOT)): sha(p) for p in frozen},
                                 'inputs_sha256': sha(output / 'inputs.json'),
                                 'catalog_sha256': sha(output / 'catalog.json'), 'protocol': protocol})
    print('Prepared and frozen model inputs; no labels included', flush=True)


def check_frozen(output):
    frozen = read(output / 'frozen.json')
    for relative, expected in frozen['files'].items():
        assert sha(ROOT / relative) == expected, relative
    assert sha(output / 'inputs.json') == frozen['inputs_sha256']
    assert sha(output / 'catalog.json') == frozen['catalog_sha256']
    return frozen


def load_settings(path):
    values = {}
    for line in path.read_text().splitlines():
        if '=' in line and not line.lstrip().startswith('#'):
            key, value = line.split('=', 1)
            values[key.strip()] = value.strip().strip('\"\'')
    if not all(values.get(key) for key in ('API_KEY', 'BASE_URL', 'model')):
        raise ValueError('settings must define API_KEY, BASE_URL and model')
    return values


def invoke(settings, request_messages, protocol):
    body = {'model': settings['model'], 'messages': request_messages,
            'temperature': protocol['temperature'], 'max_tokens': protocol['max_tokens']}
    request = Request(settings['BASE_URL'].rstrip('/') + '/chat/completions',
                      data=json.dumps(body).encode(),
                      headers={'Authorization': 'Bearer ' + settings['API_KEY'], 'Content-Type': 'application/json'})
    start = time.monotonic()
    try:
        with urlopen(request, timeout=protocol['timeout_seconds']) as response:
            payload = json.load(response)
        choice = payload['choices'][0]
        return {'status': 'ok', 'text': choice['message']['content'],
                'returned_model': payload.get('model'), 'usage': payload.get('usage'),
                'finish_reason': choice.get('finish_reason'), 'seconds': time.monotonic() - start}
    except HTTPError as exc:
        # Never serialize HTTP response bodies, headers, credentials or endpoint URLs.
        return {'status': 'transport_error', 'error_type': 'HTTPError', 'http_status': exc.code}
    except (URLError, TimeoutError, OSError, ValueError, KeyError, IndexError) as exc:
        return {'status': 'transport_error', 'error_type': type(exc).__name__}


def parse_prediction(text):
    prediction = json.loads(text)
    if not isinstance(prediction, dict) or prediction.get('action') not in ('query', 'uncovered', 'clarify'):
        raise ValueError('invalid routing action')
    if prediction['action'] == 'query':
        request = prediction.get('request')
        if not isinstance(request, dict) or set(request) != {'entity', 'relations', 'context'}:
            raise ValueError('query requires entity, relations, context')
        if (not isinstance(request['entity'], str) or not isinstance(request['relations'], list)
                or not request['relations'] or not all(isinstance(r, str) for r in request['relations'])
                or not isinstance(request['context'], dict)):
            raise ValueError('invalid query parameter types')
    elif prediction.get('request') is not None:
        raise ValueError('uncovered/clarify must have null request')
    return prediction


def execute(graph, prediction):
    if prediction['action'] != 'query':
        return {'status': prediction['action'], 'results': []}
    return graph.query(**prediction['request'])


def run(output, settings_path):
    frozen = check_frozen(output)
    protocol = frozen['protocol']
    settings = load_settings(settings_path)
    inputs = read(output / 'inputs.json')
    graph = pilot_graph()
    # Exclusive creation: one frozen attempt, no silent reruns or answer-driven repair.
    with (output / 'attempts.jsonl').open('x') as log:
        write(output / 'run.json', {'requested_model': settings['model'],
                                  'temperature': protocol['temperature'], 'max_tokens': protocol['max_tokens'],
                                  'automatic_retries': 0, 'history_between_cases': False})
        for item in inputs:
            response = invoke(settings, item['messages'], protocol)
            record = {'id': item['id'], 'response': response}
            if response['status'] == 'ok':
                try:
                    prediction = parse_prediction(response['text'])
                    record['prediction'] = prediction
                    record['execution'] = execute(graph, prediction)
                except (ValueError, TypeError) as exc:
                    record['execution'] = {'status': 'invalid_request', 'error_type': type(exc).__name__, 'results': []}
            log.write(json.dumps(record, ensure_ascii=False) + '\n')
            log.flush()
            print(item['id'], response['status'], record.get('execution', {}).get('status', ''), flush=True)
            # Infrastructure outage should not waste the remaining calls.
            if response['status'] != 'ok':
                break
    check_frozen(output)


def same_value(left, right):
    return type(left) is type(right) and left == right


def score_case(annotation, record):
    expected = annotation['expected']
    reference = annotation['reference_request']
    prediction = record.get('prediction', {})
    execution = record.get('execution', {})
    action = prediction.get('action')
    request = prediction.get('request') or {}
    context = request.get('context') or {}
    facts = execution.get('results', [])
    ids = {f['id'] for f in facts}
    targets = set(expected['fact_ids'])
    provided = set(context)
    incorrect = [key for key in context if key not in reference['context'] or
                 not same_value(context[key], reference['context'][key])]
    missing = sorted(set(reference['context']) - provided)
    exact = (action == 'query' and request.get('entity') == reference['entity'] and
             set(request.get('relations', [])) == set(reference['relations']) and not incorrect and not missing)
    valid_query = action == 'query' and execution.get('status') not in (None, 'invalid_request')
    faithful = valid_query and not incorrect
    states = {f['id']: f['condition_state'] for f in facts}
    covered_gap = expected['status'] in ('entity_not_found', 'relation_not_covered')
    outcome = ((action == 'uncovered' and covered_gap) or
               (valid_query and execution['status'] == expected['status'] and ids == targets
                and states == expected['condition_states']))
    evidence = [e for f in facts for e in f['evidence']]
    pages = list(dict.fromkeys(e['pdf_page'] for e in evidence))[:4]
    support = set(expected['support_pages'])
    lookup = annotation['group'] == 'source_lookup'
    return {'id': annotation['id'], 'group': annotation['group'], 'action': action,
            'transport_ok': record.get('response', {}).get('status') == 'ok',
            'exact_reference_request': exact, 'valid_query': valid_query,
            'context_faithful': faithful if action == 'query' else None,
            'incorrect_context_fields': incorrect, 'missing_reference_context_fields': missing if action == 'query' else [],
            'outcome_matches_reference': bool(outcome),
            'fact_recall': len(ids & targets) / len(targets) if targets else None,
            'fact_precision': len(ids & targets) / len(ids) if ids else None,
            'condition_states_match': states == expected['condition_states'] if targets else None,
            'support_page_recall': len(set(pages) & support) / len(support) if lookup else None,
            'pages': pages, 'returned_fact_ids': sorted(ids), 'expected_fact_ids': sorted(targets),
            'returned_status': execution.get('status'), 'expected_status': expected['status']}


def score(output):
    check_frozen(output)
    annotations = lines(DATASET / 'annotations.jsonl')
    attempts = lines(output / 'attempts.jsonl')
    records = {r['id']: r for r in attempts}
    assert len(records) == len(attempts), 'duplicate attempts'
    scored = [score_case(a, records.get(a['id'], {})) for a in annotations]
    def metric(key):
        values = [r[key] for r in scored if r[key] is not None]
        return {'n': len(values), 'mean': sum(values) / len(values) if values else None}
    summary = {'cases': len(scored), 'attempted': len(attempts), 'model': read(output / 'run.json')['requested_model'],
               'metrics': {key: metric(key) for key in ('transport_ok', 'exact_reference_request', 'valid_query',
                          'context_faithful', 'outcome_matches_reference', 'fact_recall', 'fact_precision',
                          'condition_states_match', 'support_page_recall')},
               'mismatched_cases': [r['id'] for r in scored if not r['outcome_matches_reference']],
               'limitations': read(DATASET / 'protocol.json')['limitations']}
    write(output / 'scores.json', scored)
    write(output / 'summary.json', summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['prepare', 'run', 'score'])
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--settings', type=Path, default=ROOT / 'llm-setting.txt')
    args = parser.parse_args()
    if args.command == 'prepare':
        prepare(args.output)
    elif args.command == 'run':
        run(args.output, args.settings)
    else:
        score(args.output)


if __name__ == '__main__':
    main()
