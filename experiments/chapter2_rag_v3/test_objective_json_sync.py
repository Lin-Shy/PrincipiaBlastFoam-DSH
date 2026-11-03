import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import objective_json_sync as sync


class SyncTests(unittest.TestCase):
    def test_preserves_unrelated_text_and_updates_objective_markers(self):
        names = {
            'graduation-manuscript/docs/abstract.tex': '% OBJECTIVE-20261102-BEGIN\nold\n% OBJECTIVE-20261102-END\nOn 172 objective items, expert review is pending.\nDev40/Test160',
            'graduation-manuscript/docs/chap05.tex': '客观题补充评价覆盖172题和4472个任务，旧内容；题目共享事实且缺少独立领域专家复核。',
            'graduation-manuscript/docs/appendix_ch02.tex': '% OBJECTIVE-20261102-BEGIN\nold\n% OBJECTIVE-20261102-END',
            'graduation-manuscript/docs/chap02_objective_review.tex': 'old',
            'graduation-research/chapters/chapter02.md': '% OBJECTIVE-20261102-BEGIN\nold\n% OBJECTIVE-20261102-END'}
        with tempfile.TemporaryDirectory(dir=sync.exp.WORK / 'PrincipiaBlastFoam-DSH/.local') as temp:
            work = Path(temp)
            for name, content in names.items():
                dest = work / 'graduation-thesis-materials' / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_text(content, encoding='utf8')
            out = work / 'experiment'; (out/'results').mkdir(parents=True)
            snap = {'status': 'closed', 'configurations': [{'model': 'qwen3-8b', 'method': 'graph', 'accuracy': .4},
                    {'model': 'qwen3-14b', 'method': 'graph', 'accuracy': .5}]}
            (out/'results/snapshot.json').write_text(json.dumps(snap), encoding='utf8')
            audit = {'status': 'passed', 'snapshot_sha256': sync.exp.sha(out/'results/snapshot.json')}
            (out/'results/json_audit.json').write_text(json.dumps(audit), encoding='utf8')
            with patch.object(sync.exp, 'WORK', work), patch.object(sync.full, 'OUT', out):
                sync.main()
            text = (work/'graduation-thesis-materials/graduation-manuscript/docs/abstract.tex').read_text(encoding='utf8')
            self.assertIn(r'40.00\%', text)
            self.assertIn(r'50.00\%', text)
            self.assertIn('Dev40/Test160', text)
