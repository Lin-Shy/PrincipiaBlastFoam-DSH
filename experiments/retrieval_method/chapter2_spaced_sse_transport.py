"""Registered request-start spacing on top of unchanged paced SSE transport."""
from threading import Lock
import time

from chapter2_lossless_json import save
from chapter2_paced_sse_transport import install as install_paced, POLICY as PACED_POLICY

POLICY='per_model_start250ms_write128_paced2ms_sse_v4'
MIN_INTERVAL_SECONDS=.25


class StartSpacing:
    """One independent admission clock per exact model; never hold a network call."""
    def __init__(self, *, clock=time.monotonic, sleep=time.sleep):
        self.clock=clock;self.sleep=sleep
        self.locks={model:Lock() for model in ('qwen3-8b','qwen3-14b')}
        self.next_start={model:None for model in self.locks}

    def wait(self,model):
        if model not in self.locks:raise ValueError('Unexpected exact model for request admission')
        began=self.clock()
        with self.locks[model]:
            target=self.next_start[model]
            while target is not None:
                remaining=target-self.clock()
                if remaining<=0:break
                self.sleep(remaining)
            admitted=self.clock()
            self.next_start[model]=admitted+MIN_INTERVAL_SECONDS
        return max(0.0,admitted-began)


def install(router,amendment_sha256):
    install_paced(router,amendment_sha256)
    original=router.RecordedProxyQwenClient;spacing=StartSpacing()

    class SpacedSSEClient(original):
        transport_policy=POLICY

        def __call__(self,body,turn):
            # The original client still reserves the physical attempt exclusively.
            # Queue waiting is not added to its network-duration measurement.
            waited=spacing.wait(self.deployment.model)
            record=super().__call__(body,turn)
            record.update(transport_policy=POLICY,base_paced_policy=PACED_POLICY,
                          request_admission_policy=POLICY,
                          request_admission_min_interval_seconds=MIN_INTERVAL_SECONDS,
                          request_admission_wait_seconds=waited)
            save(self.folder/f'{turn:02d}.json',record)
            return record

    router.RecordedProxyQwenClient=SpacedSSEClient
    return dict(policy=POLICY,base_paced_policy=PACED_POLICY,amendment_sha256=amendment_sha256,
                request_admission_min_interval_seconds=MIN_INTERVAL_SECONDS,
                logical_request_changes=False,wire_request_changes_vs_sse_v2=False,
                transport_attempts=1,content_retries=0,workers_per_model=16)
