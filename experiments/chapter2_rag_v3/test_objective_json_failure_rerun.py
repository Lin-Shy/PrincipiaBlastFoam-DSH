import unittest
from objective_json_failure_rerun import rerun_needed


class FailureSelectionTests(unittest.TestCase):
    def test_answered_tasks_are_never_resampled(self):
        self.assertFalse(rerun_needed({'status':'answered','answer':'wrong'}))
        self.assertFalse(rerun_needed({'status':'answered','answer':'unparseable explanation'}))
        for status in ('transport_error','invalid_response','completion_truncated','invalid_action','unknown_request_state'):
            self.assertTrue(rerun_needed({'status':status}))
