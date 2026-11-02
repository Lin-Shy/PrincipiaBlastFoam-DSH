"""Scheduling may change concurrency, never item ownership or call budgets."""
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import test160_resume_scores as main
import test160_capacity_monitor as monitor
from datetime import datetime, timezone


class MainDispatchTests(unittest.TestCase):
    def test_capacity_monitor_accepts_blank_jsonl_lines(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(monitor, 'BASE', Path(directory)):
            for base in (monitor.BASE, monitor.BASE/'supplement/single_pass'):
                path = base/'scoring/gpt_sol/recovery_events.jsonl'
                path.parent.mkdir(parents=True)
                path.write_text('\n\r\n'+json.dumps(dict(completed_utc='2026-11-02T09:00:00+00:00',
                                                       status='valid'))+'\n')
            self.assertEqual(len(monitor.recent_events(datetime(2026, 11, 2, tzinfo=timezone.utc))), 2)

    def test_configuration_allows_eight_main_workers_under_shared_cap(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(main, 'BASE', Path(directory)):
            path = main.BASE/'gpt_concurrency_control_20261102.json'
            path.write_text(json.dumps(dict(gpt_main_workers=8, gpt_total_slot_cap=8)))
            self.assertEqual(main.worker_count('gpt_sol'), 8)
            self.assertEqual(main.slot_count('gpt_sol'), 8)
            self.assertEqual(main.worker_count('deepseek_flash'), 2)
            self.assertFalse(main.pause_requested('gpt_sol'))
            path.write_text(json.dumps(dict(gpt_main_workers=8, gpt_total_slot_cap=8,
                                           pause_main_dispatch=True)))
            self.assertTrue(main.pause_requested('gpt_sol'))

    def test_unbounded_configuration_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(main, 'BASE', Path(directory)):
            (main.BASE/'gpt_concurrency_control_20261102.json').write_text(
                json.dumps(dict(gpt_main_workers=32, gpt_total_slot_cap=32)))
            with self.assertRaises(AssertionError):
                main.worker_count('gpt_sol')
            with self.assertRaises(AssertionError):
                main.slot_count('gpt_sol')

    def test_same_item_lock_serializes_two_dispatchers(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            inside = []
            results = []
            def worker():
                with main.dispatch_lock(root):
                    inside.append(1)
                    results.append(len(inside))
                    time.sleep(0.03)
                    inside.pop()
            threads = [threading.Thread(target=worker) for _ in range(2)]
            for thread in threads: thread.start()
            for thread in threads: thread.join()
            self.assertEqual(results, [1, 1])
            self.assertFalse((root/'gpt_dispatch.lock').exists())

    def test_foreign_dispatch_is_skipped_before_request_preparation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'gpt_dispatch.lock').write_text('foreign-owner')
            with patch.object(main.rec, 'request', side_effect=AssertionError('must not prepare')):
                eligible, reason = main.eligible(root, 'gpt_sol', {'generation_failed': False})
            self.assertFalse(eligible)
            self.assertEqual(reason, 'scheduler_in_flight')


if __name__ == '__main__':
    unittest.main()
