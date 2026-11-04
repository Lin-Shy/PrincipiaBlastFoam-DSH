"""当前超算 Qwen3-8B 接口；独立记录实际请求，不覆盖历史实验。"""
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

from chapter2_qwen_limits import SUPERCOMPUTER_MAX_CONCURRENCY, concurrency_setting, endpoint_limiter


DEFAULT_SETTINGS = Path(__file__).resolve().parents[3] / '.env.supercomputer'


@dataclass(frozen=True)
class ModelDeployment:
    endpoint: str
    model: str
    key: str = field(repr=False)
    max_concurrency: int = SUPERCOMPUTER_MAX_CONCURRENCY


def load_model(model, path=DEFAULT_SETTINGS):
    """Read only the explicitly supplied supercomputer deployment; never fall back."""
    if model.lower() != 'qwen3-8b':
        raise ValueError('Supercomputer deployment supports Qwen3-8B only; 14B requires the proxy deployment')
    size = '8B'
    allowed = {'QWEN_SUPERCOMPUTER_API_KEY', 'QWEN_SUPERCOMPUTER_MAX_CONCURRENCY',
               'QWEN_SUPERCOMPUTER_BASE_URL', 'QWEN_SUPERCOMPUTER_MODEL'}
    values = {}
    for line in Path(path).read_text(encoding='utf-8-sig').splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        name, sep, value = line.partition('=')
        name = name.strip()
        if not sep:
            raise ValueError('Unknown, duplicate or malformed supercomputer model setting')
        if name not in allowed:
            continue
        if name in values:
            raise ValueError('Unknown, duplicate or malformed supercomputer model setting')
        values[name] = value.strip().strip('\"\'')
    base = values.get('QWEN_SUPERCOMPUTER_BASE_URL', '').rstrip('/')
    url = urlsplit(base)
    if (url.scheme != 'https' or not url.hostname or url.username
            or url.password or url.query or url.fragment or url.path != '/v1'):
        raise ValueError('Invalid supercomputer OpenAI-compatible base URL')
    key = values.get('QWEN_SUPERCOMPUTER_API_KEY', '')
    name = values.get('QWEN_SUPERCOMPUTER_MODEL', 'Qwen3-8B')
    if not key or any(c.isspace() for c in key) or key == 'replace-with-your-supercomputer-token':
        raise ValueError('Missing or invalid supercomputer API key')
    if name != 'Qwen3-8B':
        raise ValueError('Current supercomputer model identifier must be Qwen3-8B')
    maximum = concurrency_setting(values, 'QWEN_SUPERCOMPUTER_MAX_CONCURRENCY', SUPERCOMPUTER_MAX_CONCURRENCY)
    return ModelDeployment(base + '/chat/completions', name, key, maximum)


def prepare_body(body, deployment):
    """Keep decoding limits; explicitly record the documented /no_think change."""
    result = deepcopy(body)
    if result.pop('enable_thinking', False) is not False:
        raise ValueError('This supercomputer adapter is registered for non-thinking calls only')
    result['model'] = deployment.model
    messages = result.get('messages', [])
    for message in reversed(messages):
        if message.get('role') == 'user':
            content = message.get('content')
            if not isinstance(content, str):
                raise ValueError('Supercomputer non-thinking adapter requires text user content')
            if not content.rstrip().endswith('/no_think'):
                message['content'] = content + '\n/no_think'
            break
    else:
        raise ValueError('Supercomputer request has no user message')
    if result.get('stream', False):
        raise ValueError('Recorded supercomputer client requires non-streaming responses')
    result['stream'] = False
    return result


class SupercomputerQwenClient:
    """One recorded attempt per call; no silent retries or legacy endpoint use.

    This is deliberately a new execution identity. Frozen grading controllers
    require a separately registered transition before using this client.
    """
    def __init__(self, model, folder, settings_path=DEFAULT_SETTINGS, timeout=120):
        self.deployment = load_model(model, settings_path)
        self.folder = Path(folder)
        self.timeout = timeout
        self.opener = build_opener(ProxyHandler({}))
        self.limiter = endpoint_limiter(self.deployment.endpoint, self.deployment.max_concurrency)

    def __call__(self, body, turn):
        if type(turn) is not int or turn < 0:
            raise ValueError('turn must be a nonnegative integer')
        if body.get('model', 'qwen3-8b') not in {'qwen3-8b', self.deployment.model}:
            raise ValueError('Supercomputer request model must be Qwen3-8B; model substitution is forbidden')
        actual = prepare_body(body, self.deployment)
        data = json.dumps(actual, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
        self.folder.mkdir(parents=True, exist_ok=True)
        path = self.folder / f'{turn:02d}.json'
        record = dict(provider='qwen_supercomputer', endpoint=self.deployment.endpoint,
                      model=self.deployment.model, request=actual,
                      request_sha256=hashlib.sha256(data).hexdigest(),
                      started_utc=datetime.now(timezone.utc).isoformat(),
                      status='in_flight', transport_attempts=1, content_retries=0,
                      transport_route='direct_' + urlsplit(self.deployment.endpoint).scheme)
        # Exclusive creation prevents reissuing completed or unresolved calls.
        with path.open('x', encoding='utf-8') as out:
            json.dump(record, out, ensure_ascii=False, indent=2)
        request = Request(self.deployment.endpoint, data=data, headers={
            'Authorization': 'Bearer ' + self.deployment.key, 'Content-Type': 'application/json'})
        queued = time.monotonic()
        self.limiter.acquire()
        started = time.monotonic()
        record.update(admission_wait_seconds=started - queued,
                      started_utc=datetime.now(timezone.utc).isoformat(),
                      max_concurrency=self.deployment.max_concurrency)
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
            self.limiter.release()
            temp = path.with_suffix('.tmp')
            temp.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            temp.replace(path)
        return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--settings', type=Path, default=DEFAULT_SETTINGS)
    parser.add_argument('--model', required=True, choices=['qwen3-8b'])
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    client = SupercomputerQwenClient(args.model, args.output, args.settings)
    result = client({'model': args.model, 'messages': [{'role': 'user', 'content':
        'Return a JSON object with one field: "ok": true.'}], 'temperature': 0,
        'max_tokens': 64, 'enable_thinking': False,
        'response_format': {'type': 'json_object'}}, 0)
    print(json.dumps({k: result[k] for k in ('provider', 'model', 'status', 'seconds')}))
    if result['status'] != 'response':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
