from collections import Counter
from pathlib import Path
import tempfile
import unittest

from experiments.retrieval_method import graphify_query_replay as replay
from experiments.retrieval_method import graphify_query_variants as variants


class ReplayGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_exclusive_artifact_write_preserves_existing_results(self):
        io = replay.IO()
        io.write(self.root / "result.json", {"status": "first"})
        with self.assertRaises(FileExistsError):
            io.write(self.root / "result.json", {"status": "replacement"})
        self.assertEqual(io.read(self.root / "result.json"), {"status": "first"})

    def test_manifest_tamper_is_rejected(self):
        io = replay.IO()
        io.write(self.root / "artifact.json", {"value": 1})
        with self.assertRaisesRegex(ValueError, "changed"):
            replay.verify_files(self.root, {"artifact.json": "0"*64}, io)

    def test_manifest_path_cannot_escape_root(self):
        with self.assertRaisesRegex(ValueError, "escapes"):
            replay.contained(self.root, "../outside.json")

    def test_serialization_work_is_measured_for_all_strategies(self):
        counts = Counter()
        token = variants.reference.METER.set(counts)
        try:
            result = variants.reference.bounded_payload("NODE " + "x"*1500, 300, variants.wire)
        finally:
            variants.reference.METER.reset(token)
        self.assertTrue(result["truncated"])
        self.assertGreater(counts["json_serialization_calls"], 1)
        self.assertGreater(counts["json_serialized_characters"], 1500)

    def test_sources_only_from_provenance_not_arbitrary_labels(self):
        result = {"graph_navigation": "NODE tutorials/wrong [src=tutorials/right loc=L1]\n"
            "EDGE a --r--> b at=manual/markdown/chapter.md:L2"}
        self.assertEqual(replay.source_paths(result), ["manual/markdown/chapter.md", "tutorials/right"])


if __name__ == "__main__":
    unittest.main()
