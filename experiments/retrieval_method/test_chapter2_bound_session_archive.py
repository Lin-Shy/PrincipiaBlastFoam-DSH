from pathlib import Path
import json
import tempfile
import unittest
import zipfile

from chapter2_bound_session_archive import archive_bound, collect_bound, digest, load_prior, write_parts


class BoundArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.generation = self.root / "formal/generation_001"
        self.generation.mkdir(parents=True)
        (self.generation / "protocol.json").write_bytes(b'{"ordinary":true}')

    def session(self, name="ordinary/model/r01", question="Q1", diagnostic=False):
        folder = self.generation / name / "sessions" / question
        folder.mkdir(parents=True)
        protocol = self.generation / ("diagnostic-protocol.json" if diagnostic else "protocol.json")
        if diagnostic:
            protocol.write_bytes(b'{"diagnostic":true}')
        value = dict(formal_result=True, formal_cell_id=name, protocol_sha256=digest(protocol.read_bytes()), answer="literal \\udb06 remains literal")
        data = json.dumps(value).encode()
        (folder / "result.json").write_bytes(data)
        (folder / "result-binding.json").write_text(json.dumps(dict(result_sha256=digest(data), protocol_sha256=value["protocol_sha256"], cell_id=name)))
        (folder / "requests").mkdir()
        (folder / "requests/00.sse").write_bytes(b'event: data\ndata: {"delta":"raw"}\n\n')
        return folder

    def test_unbound_inflight_folder_excluded_and_raw_bytes_roundtrip(self):
        self.session()
        live = self.generation / "ordinary/model/r01/sessions/Q2/requests"
        live.mkdir(parents=True)
        (live / "00.json").write_bytes(b'{"unfinished":')
        (live.parent / "result.json").write_bytes(b'partial')
        out = self.root / "archives/one"
        r = archive_bound(self.root, out, [], part_source_limit=1024)
        self.assertEqual(r["terminal_sessions_in_snapshot"], 1)
        self.assertFalse(any("Q2" in s for s in r["files_sha256"]))
        for part in r["parts"]:
            with zipfile.ZipFile(out / part["path"]) as z:
                for name in z.namelist():
                    self.assertEqual(z.read(name), (self.root / name).read_bytes())
        self.assertEqual(r["model_calls"], 0)

    def test_diagnostic_protocol_selected_by_hash_not_guessed_folder_name(self):
        self.session(name="separate/diagnostic/r01", diagnostic=True)
        files, sessions = collect_bound(self.root, self.generation)
        self.assertEqual(len(sessions), 1)
        self.assertIn("formal/generation_001/diagnostic-protocol.json", files)

    def test_tampered_result_binding_rejected_before_output_creation(self):
        folder = self.session()
        (folder / "result.json").write_bytes(b'{}')
        out = self.root / "archives/bad"
        with self.assertRaises(ValueError):
            archive_bound(self.root, out, [])
        self.assertFalse(out.exists())

    def test_disjoint_delta_chain_and_prior_original_mutation(self):
        self.session()
        first = self.root / "archives/one"
        r1 = archive_bound(self.root, first, [])
        self.session(question="Q2")
        second = self.root / "archives/two"
        r2 = archive_bound(self.root, second, [first / "manifest.json"])
        self.assertFalse(set(r1["files_sha256"]) & set(r2["files_sha256"]))
        self.assertEqual(r2["terminal_sessions_in_snapshot"], 2)
        (self.generation / "protocol.json").write_bytes(b'changed')
        with self.assertRaises(ValueError):
            load_prior(self.root, [first / "manifest.json"])

    def test_overlapping_prior_manifests_rejected(self):
        source = self.root / "payload"
        source.write_bytes(b'same')
        paths = []
        for n in range(2):
            path = self.root / f"prior{n}.json"
            path.write_text(json.dumps(dict(files_sha256={"payload": digest(b'same')})))
            paths.append(path)
        with self.assertRaisesRegex(ValueError, "Overlapping"):
            load_prior(self.root, paths)

    def test_part_limit_and_changed_snapshot_input(self):
        out = self.root / "parts"
        out.mkdir()
        files = {}
        for name in ["a", "b", "c"]:
            (self.root / name).write_bytes(bytes([len(files)]) * 8)
            files[name] = digest((self.root / name).read_bytes())
        parts = write_parts(self.root, out, files, 10)
        self.assertEqual(len(parts), 3)
        self.assertTrue(all(p["source_bytes"] <= 10 for p in parts))
        (self.root / "a").write_bytes(b'changed!')
        other = self.root / "changed"
        other.mkdir()
        with self.assertRaisesRegex(ValueError, "changed"):
            write_parts(self.root, other, files, 10)

    def test_prior_path_escape_and_oversized_input_rejected(self):
        outside = self.root.parent / "must-not-read-unrelated"
        prior = self.root / "escape.json"
        prior.write_text(json.dumps(dict(files_sha256={"../must-not-read-unrelated": "0"*64})))
        with self.assertRaises(ValueError):
            load_prior(self.root, [prior])
        self.assertFalse(outside.exists())
        (self.root / "large").write_bytes(b'12345')
        out = self.root / "oversized"
        out.mkdir()
        with self.assertRaisesRegex(ValueError, "Single input"):
            write_parts(self.root, out, {"large": digest(b'12345')}, 4)


if __name__ == "__main__":
    unittest.main()
