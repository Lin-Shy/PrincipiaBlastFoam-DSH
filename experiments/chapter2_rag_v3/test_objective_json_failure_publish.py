import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import objective_json_failure_publish as publish


class FailurePublishTests(unittest.TestCase):
    def test_reports_recovery_and_preserves_other_text(self):
        names={
            'graduation-manuscript/docs/abstract.tex':'% OBJECTIVE-20261102-BEGIN\nold\n% OBJECTIVE-20261102-END\nOn 172 objective items, expert review is pending.\nDev40/Test160',
            'graduation-manuscript/docs/chap05.tex':'客观题补充评价覆盖172题和4472个任务，题目共享事实且缺少独立领域专家复核。',
            'graduation-manuscript/docs/appendix_ch02.tex':'% OBJECTIVE-20261102-BEGIN\nold\n% OBJECTIVE-20261102-END',
            'graduation-manuscript/docs/chap02_objective_review.tex':'old',
            'graduation-research/chapters/chapter02.md':'% OBJECTIVE-20261102-BEGIN\nold\n% OBJECTIVE-20261102-END'}
        with tempfile.TemporaryDirectory(dir=publish.exp.WORK/'PrincipiaBlastFoam-DSH/.local') as temp:
            work=Path(temp);ms=work/'graduation-thesis-materials/graduation-manuscript';(ms/'assets').mkdir(parents=True)
            for name,content in names.items():
                dest=work/'graduation-thesis-materials'/name;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_text(content,encoding='utf8')
            out=work/'run';(out/'results').mkdir(parents=True)
            shutil.copyfile(publish.exp.BASE/'objective_json_v4/results/snapshot.json',out/'results/snapshot.json')
            (out/'results/json_audit.json').write_text(json.dumps(dict(status='passed',snapshot_sha256=publish.exp.sha(out/'results/snapshot.json'),
                rerun=915,rerun_answered=700,rerun_format_valid=680)),encoding='utf8')
            with patch.object(publish.exp,'WORK',work),patch.object(publish.run,'OUT',out),patch.object(publish.full,'OUT',out):publish.main()
            text=(ms/'docs/chap02_objective_results.tex').read_text(encoding='utf8')
            self.assertIn('915项生成失败',text);self.assertIn('700份回答',text)
            self.assertIn('objective_json_v5_failure_rerun/',(ms/'docs/appendix_ch02.tex').read_text(encoding='utf8'))
            self.assertIn('Dev40/Test160',(ms/'docs/abstract.tex').read_text(encoding='utf8'))
