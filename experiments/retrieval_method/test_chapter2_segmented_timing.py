"""分段计时的回归测试：多次搜索、模型核验调用与失败重试。"""
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from chapter2_segmented_timing import record_for_session, stage_summary


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


class TimingTest(unittest.TestCase):
    def test_all_model_calls_and_retries_are_counted(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory) / "arm"
            session = run / "sessions" / "Q1--graph_first--r2"
            save(session / "result.json", {"id": "Q1", "item_id": "family", "replicate": 2,
                    "status": "complete", "events": [
                        {"action": {"action": "locate"}, "accounting": {"seconds": .3}},
                        {"action": {"action": "source"}, "accounting": {"seconds": .2}},
                        {"action": {"action": "finish"}}]})
            save(session / "invocations" / "1.json", {"replay": False, "elapsed_seconds": 2.5})
            save(session / "step-01.json", {"request_sha256": "a", "events": [
                {"status": "transport_error", "seconds": .5}, {"status": "response", "seconds": .7}]})
            save(session / "plan.json", {"request_sha256": "b", "events": [{"status": "response", "seconds": .4}]})
            save(session / "claim-check.json", {"request_sha256": "c", "events": [{"status": "response", "seconds": .1}]})
            row = record_for_session(run, session, "principia_index_free", "holdout", "quality", 4)
            self.assertAlmostEqual(row["search_seconds"], .5)
            self.assertAlmostEqual(row["answer_seconds"], 1.7)
            self.assertEqual(row["answer_attempts"], 4)
            self.assertEqual(row["failed_answer_attempts"], 1)
            self.assertEqual(row["end_to_end_seconds"], 2.5)

    def test_p95_interpolates_and_keeps_sample_count(self):
        self.assertEqual(stage_summary([1, 2, 3, 4])["completed_samples"], 4)
        self.assertAlmostEqual(stage_summary([1, 2, 3, 4])["p95_seconds"], 3.85)


if __name__ == "__main__":
    unittest.main()
