"""Registered transport-only adapter: split HTTPS writes, preserve payload bytes.

Use through an explicit immutable amendment. No model, message, generation
parameter, endpoint, certificate check, retry or concurrency change is permitted.
"""
import http.client
import json
import ssl
from urllib.request import ProxyHandler, HTTPSHandler, build_opener

POLICY = 'direct_https_tls12_write512_v1'
WRITE_BYTES = 512


class SplitTLSConnection(http.client.HTTPSConnection):
    def send(self, data):
        if not isinstance(data, (bytes, bytearray, memoryview)):
            raise TypeError('Registered JSON transport accepts bytes only')
        for start in range(0, len(data), WRITE_BYTES):
            super().send(data[start:start + WRITE_BYTES])


class SplitTLSHandler(HTTPSHandler):
    def https_open(self, request):
        return self.do_open(SplitTLSConnection, request, context=self._context)


def install(router, amendment_sha256):
    """Add a traced adapter to this process's frozen router, without editing it."""
    if (not isinstance(amendment_sha256, str) or len(amendment_sha256) != 64
            or any(c not in '0123456789abcdef' for c in amendment_sha256)):
        raise ValueError('Frozen transport amendment SHA-256 required')
    original = router.RecordedProxyQwenClient
    if getattr(original, 'transport_policy', None):
        raise ValueError('Transport adapter already installed')

    class AdaptedProxyClient(original):
        transport_policy = POLICY

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            context = ssl.create_default_context()
            context.minimum_version = context.maximum_version = ssl.TLSVersion.TLSv1_2
            self.opener = build_opener(ProxyHandler({}), SplitTLSHandler(context=context))

        def __call__(self, body, turn):
            # The original client owns the exclusive request, exact serialization,
            # single network attempt, failure retention and model identity check.
            record = super().__call__(body, turn)
            record.update(transport_policy=POLICY, transport_revision_sha256=amendment_sha256,
                          tls_application_write_limit_bytes=WRITE_BYTES)
            path = self.folder / f'{turn:02d}.json'
            temp = path.with_suffix('.tls.tmp')
            temp.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            temp.replace(path)
            return record

    router.RecordedProxyQwenClient = AdaptedProxyClient
    return dict(policy=POLICY, amendment_sha256=amendment_sha256,
                tls_application_write_limit_bytes=WRITE_BYTES, transport_attempts=1,
                content_retries=0, request_body_changes=False)
