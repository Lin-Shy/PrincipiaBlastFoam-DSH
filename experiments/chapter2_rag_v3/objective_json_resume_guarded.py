"""Resume only unstarted 8B tasks with an outage circuit breaker.

Recorded terminal results and folders with uncertain requests are never retried.
The underlying frozen runner retains the request and infrastructure-error logs.
"""
import json
import threading
from urllib.request import Request, ProxyHandler, build_opener
import objective_experiment as base
import objective_json_full as full


class CircuitBreaker:
    def __init__(self, threshold=3):
        self.threshold = threshold
        self.failures = 0
        self.lock = threading.Lock()

    def observe(self, response):
        with self.lock:
            if response.get('status') in ('transport_error', 'invalid_response'):
                self.failures += 1
            elif response.get('status') == 'response':
                self.failures = 0
            if self.failures >= self.threshold:
                raise RuntimeError('8B service circuit breaker: repeated transport or invalid responses')


def health():
    from chapter2_qwen_local import load_model
    model = load_model('qwen3-8b', base.SUPERCOMPUTER_SETTINGS)
    url = model.endpoint.rsplit('/chat/completions', 1)[0] + '/models'
    req = Request(url, headers={'Authorization': 'Bearer ' + model.key})
    with build_opener(ProxyHandler({})).open(req, timeout=15) as response:
        payload = json.loads(response.read())
    if not isinstance(payload, dict) or not isinstance(payload.get('data'), list):
        raise RuntimeError('8B model-list health check did not return a JSON model list')
    if not any(item.get('id') == model.model for item in payload['data'] if isinstance(item, dict)):
        raise RuntimeError('Registered 8B deployment is not in the model list')


def main():
    health()
    full.use_full()
    original = base.supercomputer_client
    circuit = CircuitBreaker()
    def guarded(folder):
        client = original(folder)
        def call(body, turn):
            result = client(body, turn)
            circuit.observe(result)
            return result
        return call
    base.supercomputer_client = guarded
    base.run('qwen3_8b')


if __name__ == '__main__':
    main()
