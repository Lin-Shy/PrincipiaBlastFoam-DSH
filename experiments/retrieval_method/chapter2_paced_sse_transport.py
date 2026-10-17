"""Explicitly registered HTTPS pacing; reuse the exact v2 SSE body and parser."""
import http.client
import json
import ssl
import time
from urllib.request import HTTPSHandler,ProxyHandler,build_opener

from chapter2_lossless_json import save
from chapter2_sse_record_transport import install as install_sse, POLICY as SSE_POLICY

POLICY='direct_https_tls12_write128_paced2ms_sse_v3'
WRITE_BYTES=128
PAUSE_SECONDS=.002


class PacedTLSConnection(http.client.HTTPSConnection):
    def send(self,data):
        if not isinstance(data,(bytes,bytearray,memoryview)):
            raise TypeError('Registered JSON transport accepts bytes only')
        for start in range(0,len(data),WRITE_BYTES):
            super().send(data[start:start+WRITE_BYTES])
            time.sleep(PAUSE_SECONDS)


class PacedTLSHandler(HTTPSHandler):
    def https_open(self,request):
        return self.do_open(PacedTLSConnection,request,context=self._context)


def install(router,amendment_sha256):
    install_sse(router,amendment_sha256)
    original=router.RecordedProxyQwenClient

    class PacedSSEClient(original):
        transport_policy=POLICY
        def __init__(self,*args,**kwargs):
            super().__init__(*args,**kwargs)
            context=ssl.create_default_context()
            context.minimum_version=context.maximum_version=ssl.TLSVersion.TLSv1_2
            self.opener=build_opener(ProxyHandler({}),PacedTLSHandler(context=context))

        def __call__(self,body,turn):
            record=super().__call__(body,turn)
            record.update(transport_policy=POLICY,base_sse_policy=SSE_POLICY,
                          tls_application_write_limit_bytes=WRITE_BYTES,
                          tls_inter_write_pause_seconds=PAUSE_SECONDS)
            save(self.folder/f'{turn:02d}.json',record)
            return record

    router.RecordedProxyQwenClient=PacedSSEClient
    return dict(policy=POLICY,base_sse_policy=SSE_POLICY,amendment_sha256=amendment_sha256,
                tls_application_write_limit_bytes=WRITE_BYTES,tls_inter_write_pause_seconds=PAUSE_SECONDS,
                logical_request_changes=False,wire_request_changes_vs_sse_v2=False,
                transport_attempts=1,content_retries=0)
