import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import objective_json_transition_publish as publish


class TransitionPublishTests(unittest.TestCase):
    def test_incident_caveat_and_snapshot_path(self):
        names = {
            'graduation-manuscript/docs/abstract.tex': '% OBJECTIVE-20261102-BEGIN\nold\n% OBJECTIVE-20261102-END\nOn 172 objective items, expert review is pending.',
            'graduation-manuscript/docs/chap05.tex': '客观题补充评价覆盖172题和4472个任务，旧内容；题目共享事实且缺少独立领域专家复核。',
            'graduation-manuscript/docs/appendix_ch02.tex': '% OBJECTIVE-20261102-BEGIN\nold\n% OBJECTIVE-20261102-END',
            'graduation-manuscript/docs/chap02_objective_review.tex': 'old',
            'graduation-research/chapters/chapter02.md': '% OBJECTIVE-20261102-BEGIN\nold\n% OBJECTIVE-20261102-END'}
        with tempfile.TemporaryDirectory(dir=publish.exp.WORK/'PrincipiaBlastFoam-DSH/.local') as temp:
            work = Path(temp); ms = work/'graduation-thesis-materials/graduation-manuscript'
            (ms/'assets').mkdir(parents=True)
            for name, content in names.items():
                dest = work/'graduation-thesis-materials'/name; dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(content, encoding='utf8')
            out = work/'run'; (out/'results').mkdir(parents=True)
            shutil.copyfile(publish.transition.OUT/'results/snapshot.json', out/'results/snapshot.json')
            (out/'results/json_audit.json').write_text(json.dumps(dict(status='passed',
                snapshot_sha256=publish.exp.sha(out/'results/snapshot.json'))), encoding='utf8')
            with patch.object(publish.exp, 'WORK', work), patch.object(publish.transition, 'OUT', out), \
                    patch.object(publish.full, 'OUT', out):
                publish.main()
            text = (ms/'docs/chap02_objective_results.tex').read_text(encoding='utf8')
            self.assertIn('649项', text)
            self.assertIn('7项', text)
            self.assertIn('objective_json_v4/', (ms/'docs/appendix_ch02.tex').read_text(encoding='utf8'))
