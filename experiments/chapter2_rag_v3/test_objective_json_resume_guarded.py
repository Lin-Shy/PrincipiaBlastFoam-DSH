import unittest
from objective_json_resume_guarded import CircuitBreaker


class CircuitTests(unittest.TestCase):
    def test_stops_after_consecutive_failures_and_resets_on_success(self):
        breaker = CircuitBreaker(3)
        breaker.observe({'status': 'invalid_response'})
        breaker.observe({'status': 'response'})
        breaker.observe({'status': 'transport_error'})
        breaker.observe({'status': 'invalid_response'})
        with self.assertRaises(RuntimeError):
            breaker.observe({'status': 'transport_error'})
