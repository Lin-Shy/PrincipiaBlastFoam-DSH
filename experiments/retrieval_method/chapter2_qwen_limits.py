"""当前 Qwen 服务的进程内并发上限；不修改冻结控制器的协议。"""
from threading import BoundedSemaphore, Lock


LOCAL_MAX_CONCURRENCY = 8
PROXY_MAX_CONCURRENCY = 20
_lock = Lock()
_limits = {}


def concurrency_setting(values, name, ceiling):
    value = values.get(name, str(ceiling))
    if not value.isascii() or not value.isdigit() or not 1 <= int(value) <= ceiling:
        raise ValueError(f'{name} must be an integer between 1 and {ceiling}')
    return int(value)


def endpoint_limiter(endpoint, maximum):
    """Share one limit across client instances; reject conflicting configurations."""
    with _lock:
        if endpoint not in _limits:
            _limits[endpoint] = (maximum, BoundedSemaphore(maximum))
        configured, limiter = _limits[endpoint]
        if configured != maximum:
            raise ValueError('Conflicting concurrency limits for one endpoint; restart with one configuration')
        return limiter
