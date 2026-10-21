"""Bound independent answer workers; drain admitted work and never retry failures."""
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from threading import Lock


def run_bounded(items, worker, on_result, max_workers):
    if type(max_workers) is not int or not 1 <= max_workers <= 8:
        raise ValueError('Registered worker bound must be between one and eight')
    source = iter(items);pending = {};errors = [];exhausted = False
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        while pending or not exhausted:
            while not errors and not exhausted and len(pending) < max_workers:
                try:item = next(source)
                except StopIteration:exhausted = True;break
                pending[pool.submit(worker,item)] = item
            if not pending:break
            done,_ = wait(pending,return_when=FIRST_COMPLETED)
            for future in done:
                item = pending.pop(future)
                try:on_result(item,future.result())
                except Exception as exc:errors.append(exc)
            if errors:exhausted = True
        # Every already admitted worker is observed before propagating failure.
    if errors:raise errors[0]


class LockedFrozenParser:
    """Serialize the frozen parser's module-level request adapters, restoring both."""
    def __init__(self, partial, reasoning):
        self.partial = partial;self.reasoning = reasoning;self.lock = Lock()

    def __call__(self, responses, payload, actual):
        with self.lock:
            partial = self.partial
            old_requests = partial.source_free_requests
            old_parse = partial.parse_source_free_judgments
            try:
                partial.source_free_requests = lambda ignored:actual
                partial.parse_source_free_judgments = lambda rs,value:self.reasoning.parse_reasoning_judgments(rs,value,requests=actual)
                return partial.parse_partial_judgments(responses,payload)
            finally:
                partial.source_free_requests = old_requests
                partial.parse_source_free_judgments = old_parse
