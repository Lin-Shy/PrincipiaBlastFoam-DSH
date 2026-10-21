"""用户授权的代理接入；保持冻结请求体，逐次记录供应商来源，不保存凭据。"""
import hashlib
import json
from pathlib import Path
import threading
from urllib.parse import urlsplit

from chapter2_qwen_limits import PROXY_MAX_CONCURRENCY, concurrency_setting


def load_settings(path):
    values = {}
    for line in Path(path).read_text(encoding='utf-8-sig').splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        name, value = (part.strip() for part in line.split('=', 1))
        if name not in {'QWEN_PROXY_API_KEY', 'QWEN_PROXY_BASE_URL', 'QWEN_PROXY_MAX_CONCURRENCY'} or name in values:
            raise ValueError('Unknown or duplicate proxy setting')
        values[name] = value.strip('\"\'')
    base = values.get('QWEN_PROXY_BASE_URL', '').rstrip('/')
    url = urlsplit(base)
    if url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ValueError('Invalid proxy HTTPS base URL')
    key = values.get('QWEN_PROXY_API_KEY', '')
    if not key or any(ch.isspace() for ch in key):
        raise ValueError('Missing or invalid proxy key')
    maximum = concurrency_setting(values, 'QWEN_PROXY_MAX_CONCURRENCY', PROXY_MAX_CONCURRENCY)
    return base, key, maximum


def settings(path):
    """Keep the legacy two-value interface for historical offline consumers."""
    return load_settings(path)[:2]


def read_settings(path):
    return settings(path)[1]


def configure_qa(qa, path, expected_base):
    from chapter2_aliyun_config import configure_qa as frozen_configure
    frozen_configure(qa)  # 原冻结模型、请求生成函数与参数逐字复用。
    base, _ = settings(path)
    if base != expected_base:
        raise ValueError('Proxy endpoint differs from sealed amendment')
    qa.ENDPOINT = base + '/chat/completions'


def install_provenance(net, qa, root, amendment, config_sha):
    context = threading.local()
    original_fetch, original_open = net.fetch, net.urlopen
    ledger = amendment / 'provider_attempts'
    ledger.mkdir(exist_ok=True)

    def save(file, value):
        temp = file.with_suffix('.tmp')
        temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
        temp.replace(file)

    def fetch(folder, name, body, key):
        context.file = Path(folder) / (name + '.json')
        try:
            value = original_fetch(folder, name, body, key)
            if value.get('status') == 'response' and value['raw_response'].get('model') != qa.MODEL:
                raise ValueError('Received model identity mismatch; preserved, no quality retry')
            return value
        finally:
            context.file = None

    def open_request(request, **kwargs):
        file = context.file
        record = json.loads(file.read_text())
        event = record['events'][-1]
        body = json.loads(request.data)
        if qa.digest(qa.wire(body)) != record['request_sha256'] or request.full_url != qa.ENDPOINT:
            raise ValueError('Provider request provenance mismatch')
        target = ledger / (str(event['started_unix_ns']) + '.json')
        value = {'provider': 'qwen_proxy', 'endpoint': qa.ENDPOINT,
                 'request_path': str(file.relative_to(root)), 'request_sha256': record['request_sha256'],
                 'started_unix_ns': event['started_unix_ns'], 'status': 'in_flight',
                 'execution_amendment_sha256': config_sha}
        if target.exists():
            raise FileExistsError('Duplicate provider attempt identity')
        save(target, value)
        try:
            response = original_open(request, **kwargs)
        except BaseException as error:
            value.update(status='transport_error', error_type=type(error).__name__, http_status=getattr(error, 'code', None))
            # 只记录固定诊断标签，不保存供应商可能回显的文本/认证信息。
            if hasattr(error, 'read'):
                try:
                    payload = error.read(16384).decode(errors='replace').lower()
                    signals = {
                        'upstream_timeout': ['timeout', 'timed out', '超时'],
                        'rate_limit': ['rate limit', 'too many requests', '限流', '并发'],
                        'upstream_unavailable': ['bad gateway', 'upstream', '上游', '无可用'],
                        'context_length': ['context length', 'maximum context', '上下文长度'],
                        'quota_exhaustion': ['insufficient_quota', 'quota exhausted', 'credit exhausted', 'insufficient balance', '余额不足', '额度不足'],
                    }
                    value['error_signal_flags'] = [name for name, patterns in signals.items() if any(pattern in payload for pattern in patterns)]
                    if 'quota_exhaustion' in value['error_signal_flags']:
                        net._transport_circuit.set()
                except Exception:
                    value['error_signal_flags'] = ['diagnostic_body_unavailable']
            save(target, value)
            raise

        class Response:
            def __enter__(self):
                response.__enter__()
                return self

            def __exit__(self, *args):
                return response.__exit__(*args)

            def read(self):
                try:
                    raw = response.read()
                except BaseException as error:
                    value.update(status='response_read_error', error_type=type(error).__name__)
                    save(target, value)
                    raise
                # 无效JSON仍原样交给冻结fetch落盘并终止，不能变成可恢复网络错误。
                try:
                    payload = json.loads(raw)
                except ValueError:
                    payload = None
                value.update(status='response',
                             response_model=payload.get('model') if isinstance(payload, dict) else None,
                             usage=payload.get('usage') if isinstance(payload, dict) else None,
                             raw_response_sha256=hashlib.sha256(raw).hexdigest())
                save(target, value)
                return raw

        return Response()

    net.fetch = fetch
    net.urlopen = open_request
