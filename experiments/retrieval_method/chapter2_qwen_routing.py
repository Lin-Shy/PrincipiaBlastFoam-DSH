"""按批量选择 Qwen 部署；冻结历史客户端保持不变。"""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import ssl
import time
from urllib.error import HTTPError
from urllib.request import Request, ProxyHandler, HTTPSHandler, build_opener

from chapter2_qwen_local import LocalModel, LocalQwenClient
from chapter2_qwen_proxy_config import settings

WORKSPACE = Path(__file__).resolve().parents[3]


class RecordedProxyQwenClient:
    """One exclusive recorded attempt; preserve the frozen proxy request body."""
    provider = 'qwen_proxy'

    def __init__(self, model, folder, settings_path=None, timeout=180):
        if model not in {'qwen3-8b', 'qwen3-14b'}:
            raise ValueError('Unsupported exact Qwen model')
        base, key = settings(settings_path or WORKSPACE / '.env.qwen_proxy')
        self.deployment = LocalModel(base + '/chat/completions', model, key)
        self.folder = Path(folder)
        self.timeout = timeout
        context = ssl.create_default_context()
        context.minimum_version = context.maximum_version = ssl.TLSVersion.TLSv1_2
        self.opener = build_opener(ProxyHandler({}), HTTPSHandler(context=context))

    def __call__(self, body, turn):
        if type(turn) is not int or turn < 0:
            raise ValueError('Invalid request identity')
        actual = deepcopy(body)
        if actual.get('model') != self.deployment.model or actual.get('stream', False):
            raise ValueError('Proxy model/stream identity differs from registered request')
        data = json.dumps(actual, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')
        self.folder.mkdir(parents=True, exist_ok=True)
        path = self.folder / f'{turn:02d}.json'
        record = dict(provider=self.provider, endpoint=self.deployment.endpoint,
            model=self.deployment.model, request=actual,
            request_sha256=hashlib.sha256(data).hexdigest(),
            started_utc=datetime.now(timezone.utc).isoformat(), status='in_flight',
            transport_attempts=1, content_retries=0, transport_route='direct_https',
            tls_version='TLSv1.2', certificate_verification=True)
        with path.open('x', encoding='utf-8') as stream:
            json.dump(record, stream, ensure_ascii=False, indent=2)
        started = time.monotonic()
        request = Request(self.deployment.endpoint, data=data, headers={
            'Authorization': 'Bearer ' + self.deployment.key, 'Content-Type': 'application/json'})
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                raw = response.read()
                record['http_status'] = response.status
            record['raw_response_sha256'] = hashlib.sha256(raw).hexdigest()
            payload = json.loads(raw)
            record['raw_response'] = record['response'] = payload
            if not isinstance(payload, dict):
                record['status'] = 'invalid_response'
            elif payload.get('model') != self.deployment.model:
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


def routed_client(model, folder, *, workload, settings_path=None, timeout=None):
    """Bulk is proxy; small diagnosis is local. No implicit failover."""
    if workload == 'bulk':
        return RecordedProxyQwenClient(model, folder, settings_path, timeout or 180)
    if workload == 'small':
        return LocalQwenClient(model, folder, settings_path or WORKSPACE / '.env.qwen_local', timeout or 120)
    raise ValueError('Workload must be explicitly bulk or small')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--workload', choices=['bulk', 'small'], required=True)
    p.add_argument('--model', choices=['qwen3-8b', 'qwen3-14b'], required=True)
    p.add_argument('--settings', type=Path)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    client = routed_client(a.model, a.output, workload=a.workload, settings_path=a.settings)
    record = client(dict(model=a.model, messages=[dict(role='user', content='Return exactly {"ok":true}.')],
        temperature=0, max_tokens=64, enable_thinking=False, response_format={'type':'json_object'}, stream=False), 0)
    print(json.dumps({k:record[k] for k in ['provider','model','status','seconds']}), flush=True)
    if record['status'] != 'response':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
