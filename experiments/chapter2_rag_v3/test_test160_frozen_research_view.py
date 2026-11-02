"""The validation view must preserve every hash check and live workspace."""
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import test160_frozen_research_view as view


class FrozenResearchViewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.review = self.root/'review/review.json'
        self.review.parent.mkdir()
        bindings = {}
        files = []
        for name in ('README.md', 'OVERVIEW.md'):
            relative = 'graduation-thesis-materials/graduation-research/'+name
            current = self.root/relative
            current.parent.mkdir(parents=True, exist_ok=True)
            current.write_bytes(b'new active document')
            snapshot = self.review.parent/name
            snapshot.write_bytes(b'frozen document')
            sha = hashlib.sha256(snapshot.read_bytes()).hexdigest()
            bindings[relative] = sha
            files.append(dict(original_path=relative, proposed_frozen_copy='review/'+name,
                              frozen_sha256=sha))
        (self.root/'other_binding').write_bytes(b'frozen source')
        bindings['other_binding'] = hashlib.sha256(b'frozen source').hexdigest()
        self.review.write_text(json.dumps(dict(files=files)), encoding='utf-8')
        self.control = self.root/'control.json'
        self.control.write_text(json.dumps(dict(exact_hash_research_copies_authorized=True)))
        manifest = self.root/'manifest.json'
        manifest.write_text(json.dumps(dict(bindings=bindings)))
        self.checked = []

        def original_authorize(path, mode):
            for rel, expected in bindings.items():
                self.checked.append(rel)
                if view.s.sha(view.s.WORKSPACE/rel) != expected:
                    raise ValueError('Frozen binding drift: '+rel)
            return 'original checks completed'

        self.ev = SimpleNamespace(authorize=original_authorize,
                                  runner=SimpleNamespace(MANIFEST=manifest))
        for obj, attr, value in [(view, 'REVIEW', self.review),
                                 (view, 'CONTROL', self.control),
                                 (view.s, 'WORKSPACE', self.root)]:
            p = patch.object(obj, attr, value)
            p.start()
            self.addCleanup(p.stop)
        view.install(self.ev)

    def test_all_checks_run_and_active_documents_stay_new(self):
        self.assertEqual(self.ev.authorize(None, 'agentic'), 'original checks completed')
        self.assertEqual(len(self.checked), 3)
        self.assertEqual(view.s.WORKSPACE, self.root)
        self.assertEqual((self.root/'graduation-thesis-materials/graduation-research/README.md').read_bytes(),
                         b'new active document')

    def test_snapshot_tamper_is_rejected(self):
        (self.review.parent/'README.md').write_bytes(b'tampered')
        with self.assertRaises(AssertionError):
            self.ev.authorize(None, 'agentic')
        self.assertEqual(view.s.WORKSPACE, self.root)

    def test_unrelated_binding_still_fails_and_workspace_restores(self):
        (self.root/'other_binding').write_bytes(b'changed source')
        with self.assertRaisesRegex(ValueError, 'other_binding'):
            self.ev.authorize(None, 'agentic')
        self.assertEqual(view.s.WORKSPACE, self.root)

    def test_unapproved_view_is_rejected(self):
        self.control.write_text(json.dumps(dict(exact_hash_research_copies_authorized=False)))
        with self.assertRaises(AssertionError):
            self.ev.authorize(None, 'agentic')


if __name__ == '__main__':
    unittest.main()
