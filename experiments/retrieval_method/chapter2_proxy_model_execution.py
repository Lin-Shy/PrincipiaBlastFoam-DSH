"""New experiments: independent proxy queues, sixteen workers per exact model."""
from collections import deque
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait

MODELS = ('qwen3-8b', 'qwen3-14b')


def run_per_model(items, worker, on_result, *, model_of, workers_per_model=16):
    """Schedule a finite, pre-registered matrix; stop admissions and drain on error.

    Worker tasks must make their model calls sequentially. All tasks competing
    for the same deployment in this process must use this one scheduler.
    This is a process-local bound, not a cross-process service quota.
    """
    if type(workers_per_model) is not int or not 1 <= workers_per_model <= 16:
        raise ValueError('Proxy per-model bound must be between one and sixteen')
    queues = {model: deque() for model in MODELS}
    for item in items:
        model = model_of(item)
        if model not in queues:
            raise ValueError('Unregistered exact proxy model')
        queues[model].append(item)
    active = dict.fromkeys(MODELS, 0)
    pending, errors = {}, []
    with ThreadPoolExecutor(max_workers=workers_per_model * len(MODELS)) as pool:
        while pending or any(queues.values()):
            if not errors:
                for model in MODELS:
                    while queues[model] and active[model] < workers_per_model:
                        item = queues[model].popleft()
                        pending[pool.submit(worker, item)] = (model, item)
                        active[model] += 1
            if not pending:
                break
            done, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in done:
                model, item = pending.pop(future)
                active[model] -= 1
                try:
                    on_result(item, future.result())
                except Exception as exc:
                    errors.append(exc)
            if errors:
                for queue in queues.values():
                    queue.clear()
    if errors:
        raise errors[0]
