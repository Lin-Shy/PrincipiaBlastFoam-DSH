"""DeepSeek official transport for the unchanged, frozen routing experiment."""
import argparse
import json
from pathlib import Path
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import evaluate_graph_routing as evaluation

ENDPOINT = 'https://api.deepseek.com/chat/completions'
MODEL = 'deepseek-flash'


def request_body(messages, protocol):
    return {'model': MODEL, 'messages': messages, 'thinking': {'type': 'disabled'},
            'temperature': protocol['temperature'], 'max_tokens': protocol['max_tokens']}


def invoke(key, messages, protocol):
    request = Request(ENDPOINT, data=json.dumps(request_body(messages, protocol)).encode(),
                      headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'})
    start = time.monotonic()
    try:
        with urlopen(request, timeout=protocol['timeout_seconds']) as response:
            payload = json.load(response)
        choice = payload['choices'][0]
        return {'status': 'ok', 'text': choice['message']['content'],
                'returned_model': payload.get('model'), 'usage': payload.get('usage'),
                'finish_reason': choice.get('finish_reason'), 'seconds': time.monotonic() - start}
    except HTTPError as exc:
        return {'status': 'transport_error', 'error_type': 'HTTPError', 'http_status': exc.code}
    except (URLError, TimeoutError, OSError, ValueError, KeyError, IndexError) as exc:
        return {'status': 'transport_error', 'error_type': type(exc).__name__}


def run(output, key_file):
    frozen = evaluation.check_frozen(output)
    adapter = evaluation.read(output / 'provider.json')
    assert adapter['adapter_sha256'] == evaluation.sha(Path(__file__))
    assert adapter['endpoint'] == ENDPOINT and adapter['model'] == MODEL
    key = key_file.read_text().strip()
    if not key or any(c.isspace() for c in key):
        raise ValueError('key file must contain one bare API key')
    graph = evaluation.pilot_graph()
    protocol = frozen['protocol']
    with (output / 'attempts.jsonl').open('x') as log:
        evaluation.write(output / 'run.json', {'requested_model': MODEL, 'provider': 'DeepSeek official',
                         'endpoint': ENDPOINT, 'thinking': 'disabled', 'temperature': protocol['temperature'],
                         'max_tokens': protocol['max_tokens'], 'automatic_retries': 0, 'history_between_cases': False})
        for item in evaluation.read(output / 'inputs.json'):
            response = invoke(key, item['messages'], protocol)
            record = {'id': item['id'], 'response': response}
            if response['status'] == 'ok':
                try:
                    prediction = evaluation.parse_prediction(response['text'])
                    record['prediction'] = prediction
                    record['execution'] = evaluation.execute(graph, prediction)
                except (ValueError, TypeError) as exc:
                    record['execution'] = {'status': 'invalid_request', 'error_type': type(exc).__name__, 'results': []}
            log.write(json.dumps(record, ensure_ascii=False) + '\n')
            log.flush()
            print(item['id'], response['status'], record.get('execution', {}).get('status', ''), flush=True)
            if response['status'] != 'ok':
                break
    evaluation.check_frozen(output)
    assert adapter['adapter_sha256'] == evaluation.sha(Path(__file__))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['prepare', 'run'])
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--key-file', type=Path)
    args = parser.parse_args()
    if args.command == 'prepare':
        evaluation.prepare(args.output)
        evaluation.write(args.output / 'provider.json', {
            'provider': 'DeepSeek official', 'endpoint': ENDPOINT, 'model': MODEL, 'thinking': 'disabled',
            'adapter_sha256': evaluation.sha(Path(__file__)),
            'change_reason': 'User requested official DeepSeek after previous provider rejected gpt-5.4.',
            'unchanged': ['messages', 'questions', 'catalog', 'annotations', 'scoring', 'temperature', 'max_tokens'],
            'model_selected_before_results': True,
            'documentation': 'https://api-docs.deepseek.com/guides/thinking_mode/'})
    else:
        if args.key_file is None:
            parser.error('--key-file required for run')
        run(args.output, args.key_file)


if __name__ == '__main__':
    main()
