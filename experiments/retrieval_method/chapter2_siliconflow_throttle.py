"""Process-wide SiliconFlow request pacing; keeps the original request ledger intact."""
import threading
import time
from urllib.error import HTTPError
from urllib.request import urlopen


class PacedUrlopen:
    def __init__(self, minimum_gap_seconds=6.0, rate_limit_pause_seconds=75.0):
        self.minimum_gap_seconds = minimum_gap_seconds
        self.rate_limit_pause_seconds = rate_limit_pause_seconds
        self.condition = threading.Condition()
        self.next_start = 0.0

    def __call__(self, request, timeout):
        with self.condition:
            while True:
                now = time.monotonic()
                wait = self.next_start - now
                if wait <= 0:
                    self.next_start = now + self.minimum_gap_seconds
                    break
                self.condition.wait(timeout=wait)
        try:
            return urlopen(request, timeout=timeout)
        except HTTPError as error:
            if error.code == 429:
                try:
                    retry_after = float(error.headers.get("Retry-After", "0"))
                except (TypeError, ValueError):
                    retry_after = 0.0
                with self.condition:
                    self.next_start = max(self.next_start, time.monotonic() +
                                          max(self.rate_limit_pause_seconds, retry_after))
                    self.condition.notify_all()
            raise
