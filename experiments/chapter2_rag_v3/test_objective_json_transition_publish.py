import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import objective_json_transition_publish as publish


class TransitionPublishTests(unittest.TestCase):
    def test_incident_caveat_and_snapshot_path(self):
        root = publish.exp.WORK/'graduation-thesis-materials'
        names = ['graduation-manuscript/docs/abstract.tex', 'graduation-manuscript/docs/chap05.tex',
                 'graduation-manuscript/docs/appendix_ch02.tex', 'graduation-manuscript/docs/chap02_objective_review.tex',
                 'graduation-research/chapters/chapter02.md']
        with tempfile.TemporaryDirectory(dir=publish.exp.WORK/'PrincipiaBlastFoam-DSH/.local') as temp:
            work = Path(temp); ms = work/'graduation-thesis-materials/graduation-manuscript'
            (ms/'assets').mkdir(parents=True)
            for name in names:
                dest = work/'graduation-thesis-materials'/name; dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(root/name, dest)
            out = work/'run'; (out/'results').mkdir(parents=True)
            shutil.copyfile(publish.exp.BASE/'objective200/results/snapshot.json', out/'results/snapshot.json')
            (out/'results/json_audit.json').write_text(json.dumps(dict(status='passed',
                snapshot_sha256=publish.exp.sha(out/'results/snapshot.json'))), encoding='utf8')
            with patch.object(publish.exp, 'WORK', work), patch.object(publish.transition, 'OUT', out), \
                    patch.object(publish.full, 'OUT', out):
                publish.main()
            text = (ms/'docs/chap02_objective_results.tex').read_text(encoding='utf8')
            self.assertIn('649项', text)
            self.assertIn('7项', text)
            self.assertIn('objective_json_v4/', (ms/'docs/appendix_ch02.tex').read_text(encoding='utf8'))
