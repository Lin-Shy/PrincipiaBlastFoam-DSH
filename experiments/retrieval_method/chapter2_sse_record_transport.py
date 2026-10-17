"""Explicitly amended SSE transport; preserve logical requests and raw wire events.

Only stream and stream_options differ from the original logical request. The
canonical completion is reconstructed from deltas without content repair/retry.
"""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import time
from urllib.error import HTTPError
from urllib.request import Request

POLICY = 'direct_https_tls12_write512_sse_v1'


class InvalidStream(ValueError):
    pass


class ModelMismatch(InvalidStream):
    pass


def wire(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')


def collect(response, model, sink, timing, started):
    """Validate a complete, single-choice SSE stream and concatenate exact deltas."""
    data, parts, reasoning = [], [], []
    identity, finish, usage, done, count = None, None, None, False, 0

    def event(lines):
        nonlocal identity, finish, usage, done, count
        if not lines:
            return
        value = b'\n'.join(lines)
        if value == b'[DONE]':
            done = True
            return
        payload = json.loads(value)
        if not isinstance(payload, dict):
            raise InvalidStream('Non-object chunk')
        if payload.get('model') != model:
            raise ModelMismatch('Unexpected stream model')
        current = (payload.get('id'), payload.get('created'))
        if identity is None:
            identity = current
        elif current != identity:
            raise InvalidStream('Changing stream identity')
        if payload.get('error'):
            raise InvalidStream('Upstream error event')
        choices = payload.get('choices')
        if not isinstance(choices, list) or len(choices) > 1:
            raise InvalidStream('Expected single choice')
        if payload.get('usage') is not None:
            if not isinstance(payload['usage'], dict):
                raise InvalidStream('Invalid usage')
            usage = payload['usage']
        for choice in choices:
            if choice.get('index') != 0 or finish is not None:
                raise InvalidStream('Unexpected choice index or post-finish delta')
            delta = choice.get('delta')
            if not isinstance(delta, dict) or delta.get('role', 'assistant') != 'assistant':
                raise InvalidStream('Invalid assistant delta')
            if delta.get('tool_calls') or delta.get('function_call'):
                raise InvalidStream('Unexpected native tool invocation')
            for field, target in [('content', parts), ('reasoning_content', reasoning)]:
                value = delta.get(field)
                if value is not None:
                    if not isinstance(value, str):
                        raise InvalidStream('Non-text delta')
                    target.append(value)
            if choice.get('finish_reason') is not None:
                finish = choice['finish_reason']
                if finish not in {'stop', 'length', 'content_filter'}:
                    raise InvalidStream('Unexpected finish reason')
        count += 1

    for line in response:
        if 'first_byte_seconds' not in timing:
            timing['first_byte_seconds'] = time.monotonic() - started
        sink.write(line)
        if line.rstrip(b'\r\n') == b'':
            event(data)
            data = []
            if done:
                break
        elif line.startswith(b'data:'):
            data.append(line[5:].lstrip(b' ').rstrip(b'\r\n'))
        elif line.startswith(b':') or line.startswith((b'event:', b'id:', b'retry:')):
            continue
        else:
            raise InvalidStream('Non-SSE response line')
    if data and not done:
        event(data)
    if not done or finish is None or identity is None:
        raise InvalidStream('Missing end marker or finish reason')
    timing.update(sse_done=True, sse_chunks=count, usage_reported=usage is not None)
    message = dict(role='assistant', content=''.join(parts))
    if reasoning:
        message['reasoning_content'] = ''.join(reasoning)
    result = dict(id=identity[0], created=identity[1], model=model, object='chat.completion',
                  choices=[dict(index=0, message=message, finish_reason=finish)])
    if usage is not None:
        result['usage'] = usage
    return result


def install(router, amendment_sha256):
    if (not isinstance(amendment_sha256, str) or len(amendment_sha256) != 64
            or any(c not in '0123456789abcdef' for c in amendment_sha256)):
        raise ValueError('Registered amendment SHA-256 required')
    original = router.RecordedProxyQwenClient
    if getattr(original, 'transport_policy', None):
        raise ValueError('Transport adapter already installed')

    class StreamingProxyClient(original):
        transport_policy = POLICY

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            import ssl
            from urllib.request import build_opener, ProxyHandler
            from chapter2_tls_record_transport import SplitTLSHandler
            context = ssl.create_default_context()
            context.minimum_version = context.maximum_version = ssl.TLSVersion.TLSv1_2
            self.opener = build_opener(ProxyHandler({}), SplitTLSHandler(context=context))

        def __call__(self, body, turn):
            if type(turn) is not int or turn < 0:
                raise ValueError('Invalid request identity')
            logical = deepcopy(body)
            if logical.get('model') != self.deployment.model or logical.get('stream', False) or 'stream_options' in logical:
                raise ValueError('Unexpected logical model or streaming request')
            actual = {**deepcopy(logical), 'stream': True, 'stream_options': {'include_usage': True}}
            data = wire(actual)
            self.folder.mkdir(parents=True, exist_ok=True)
            path = self.folder / f'{turn:02d}.json'
            raw_path = self.folder / f'{turn:02d}.sse'
            record = dict(provider=self.provider, endpoint=self.deployment.endpoint, model=self.deployment.model,
                request=actual, request_sha256=hashlib.sha256(data).hexdigest(),
                logical_request=logical, logical_request_sha256=hashlib.sha256(wire(logical)).hexdigest(),
                transport_policy=POLICY, transport_revision_sha256=amendment_sha256,
                wire_delta={'stream': True, 'stream_options': {'include_usage': True}},
                started_utc=datetime.now(timezone.utc).isoformat(), status='in_flight',
                transport_attempts=1, content_retries=0, transport_route='direct_https',
                tls_version='TLSv1.2', tls_application_write_limit_bytes=512,
                certificate_verification=True, raw_sse_file=raw_path.name)
            with path.open('x', encoding='utf-8') as output:
                json.dump(record, output, ensure_ascii=False, indent=2)
            started = time.monotonic()
            # Reserve raw evidence before the only network attempt as well.
            with raw_path.open('xb') as sink:
                try:
                    request = Request(self.deployment.endpoint, data=data, headers={
                        'Authorization': 'Bearer '+self.deployment.key, 'Content-Type': 'application/json'})
                    with self.opener.open(request, timeout=self.timeout) as response:
                        record.update(http_status=response.status, headers_seconds=time.monotonic()-started)
                        payload = collect(response, self.deployment.model, sink, record, started)
                    record.update(raw_response=payload, response=payload, status='response',
                        canonical_response_sha256=hashlib.sha256(wire(payload)).hexdigest(),
                        response_representation='canonical completion from exact SSE deltas; raw wire in raw_sse_file')
                except HTTPError as exc:
                    record.update(status='http_rejected', http_status=exc.code)
                except ModelMismatch:
                    record['status'] = 'model_mismatch'
                except (ValueError, AttributeError, TypeError, KeyError):
                    record['status'] = 'invalid_response'
                except OSError as exc:
                    record.update(status='transport_error', error_type=type(exc).__name__)
                finally:
                    record['seconds'] = time.monotonic()-started
            record['raw_response_sha256'] = hashlib.sha256(raw_path.read_bytes()).hexdigest()
            temp = path.with_suffix('.sse.tmp')
            temp.write_text(json.dumps(record, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
            temp.replace(path)
            return record

    router.RecordedProxyQwenClient = StreamingProxyClient
    return dict(policy=POLICY, amendment_sha256=amendment_sha256, request_body_changes=True,
                transport_attempts=1, content_retries=0)
