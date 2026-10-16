"""本地双 Qwen 接口；独立记录实际请求，不覆盖历史代理实验。"""
import argparse
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, ProxyHandler, build_opener


DEFAULT_SETTINGS = Path(__file__).resolve().parents[3] / '.env.qwen_local'


@dataclass(frozen=True)
class LocalModel:
    endpoint: str
    model: str
    key: str = field(repr=False)


def load_model(model, path=DEFAULT_SETTINGS):
    """Read only the explicitly supplied local deployment; never fall back."""
    size = {'qwen3-8b': '8B', 'qwen3-14b': '14B'}.get(model.lower())
    if size is None:
        raise ValueError('Local deployment supports Qwen3-8B and Qwen3-14B only')
    allowed = {'QWEN_LOCAL_API_KEY'} | {
        f'QWEN_LOCAL_{s}_{part}' for s in ('8B', '14B') for part in ('BASE_URL', 'MODEL')}
    values = {}
    for line in Path(path).read_text(encoding='utf-8-sig').splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        name, sep, value = line.partition('=')
        name = name.strip()
        if not sep or name not in allowed or name in values:
            raise ValueError('Unknown, duplicate or malformed local model setting')
        values[name] = value.strip().strip('\"\'')
    base = values.get(f'QWEN_LOCAL_{size}_BASE_URL', '').rstrip('/')
    url = urlsplit(base)
    if (url.scheme not in {'http', 'https'} or not url.hostname or url.username
            or url.password or url.query or url.fragment or url.path != '/v1'):
        raise ValueError('Invalid local OpenAI-compatible base URL')
    key = values.get('QWEN_LOCAL_API_KEY', '')
    name = values.get(f'QWEN_LOCAL_{size}_MODEL', '')
    if not key or any(c.isspace() for c in key) or key == 'replace-with-your-local-token':
        raise ValueError('Missing or invalid local API key')
    if not name or any(c.isspace() for c in name):
        raise ValueError('Missing or invalid local model identifier')
    return LocalModel(base + '/chat/completions', name, key)


def prepare_body(body, deployment):
    """Keep decoding limits; explicitly record the documented /no_think change."""
    result = deepcopy(body)
    if result.pop('enable_thinking', False) is not False:
        raise ValueError('This local adapter is registered for non-thinking calls only')
    result['model'] = deployment.model
    messages = result.get('messages', [])
    for message in reversed(messages):
        if message.get('role') == 'user':
            content = message.get('content')
            if not isinstance(content, str):
                raise ValueError('Local non-thinking adapter requires text user content')
            if not content.rstrip().endswith('/no_think'):
                message['content'] = content + '\n/no_think'
            break
    else:
        raise ValueError('Local request has no user message')
    if result.get('stream', False):
        raise ValueError('Recorded local client requires non-streaming responses')
    result['stream'] = False
    return result


class LocalQwenClient:
    """One recorded attempt per call; no silent retries or legacy endpoint use.

    This is deliberately a new execution identity. Frozen grading controllers
    require a separately registered transition before using this client.
    """
    def __init__(self, model, folder, settings_path=DEFAULT_SETTINGS, timeout=120):
        self.deployment = load_model(model, settings_path)
        self.folder = Path(folder)
        self.timeout = timeout
        self.opener = build_opener(ProxyHandler({}))

    def __call__(self, body, turn):
        if type(turn) is not int or turn < 0:
            raise ValueError('turn must be a nonnegative integer')
        actual = prepare_body(body, self.deployment)
        data = json.dumps(actual, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
        self.folder.mkdir(parents=True, exist_ok=True)
        path = self.folder / f'{turn:02d}.json'
        record = dict(provider='qwen_local', endpoint=self.deployment.endpoint,
                      model=self.deployment.model, request=actual,
                      request_sha256=hashlib.sha256(data).hexdigest(),
                      started_utc=datetime.now(timezone.utc).isoformat(),
                      status='in_flight', transport_attempts=1, content_retries=0,
                      transport_route='direct_' + urlsplit(self.deployment.endpoint).scheme)
        # Exclusive creation prevents reissuing completed or unresolved calls.
        with path.open('x', encoding='utf-8') as out:
            json.dump(record, out, ensure_ascii=False, indent=2)
        started = time.monotonic()
        request = Request(self.deployment.endpoint, data=data, headers={
            'Authorization': 'Bearer ' + self.deployment.key, 'Content-Type': 'application/json'})
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                raw = response.read()
                record['http_status'] = response.status
            record['raw_response_sha256'] = hashlib.sha256(raw).hexdigest()
            payload = json.loads(raw)
            record['raw_response'] = payload
            if payload.get('model') != self.deployment.model:
                record['status'] = 'model_mismatch'
            elif (not isinstance(payload.get('choices'), list) or not payload['choices']
                  or not isinstance(payload['choices'][0].get('message', {}).get('content'), str)):
                record['status'] = 'invalid_response'
            else:
                record['status'] = 'response'
        except HTTPError as exc:
            record.update(status='http_rejected', http_status=exc.code)
        except (ValueError, AttributeError, TypeError):
            record['status'] = 'invalid_response'
        except OSError as exc:
            record.update(status='transport_error', error_type=type(exc).__name__)
        finally:
            record['seconds'] = time.monotonic() - started
            temp = path.with_suffix('.tmp')
            temp.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            temp.replace(path)
        return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--settings', type=Path, default=DEFAULT_SETTINGS)
    parser.add_argument('--model', required=True, choices=['qwen3-8b', 'qwen3-14b'])
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    client = LocalQwenClient(args.model, args.output, args.settings)
    result = client({'model': args.model, 'messages': [{'role': 'user', 'content':
        'Return a JSON object with one field: "ok": true.'}], 'temperature': 0,
        'max_tokens': 64, 'enable_thinking': False,
        'response_format': {'type': 'json_object'}}, 0)
    print(json.dumps({k: result[k] for k in ('provider', 'model', 'status', 'seconds')}))
    if result['status'] != 'response':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
