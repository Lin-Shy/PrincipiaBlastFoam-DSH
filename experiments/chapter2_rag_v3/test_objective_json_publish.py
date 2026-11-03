import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import objective_json_publish as publish


class PublishTests(unittest.TestCase):
    def test_closed_snapshot_generates_table_and_insert(self):
        fixture = publish.exp.BASE / 'objective_json_v4/results/snapshot.json'
        with tempfile.TemporaryDirectory(dir=publish.exp.WORK/'PrincipiaBlastFoam-DSH/.local') as temp:
            work = Path(temp)
            out = work/'run'; (out/'results').mkdir(parents=True)
            shutil.copyfile(fixture, out/'results/snapshot.json')
            manuscript = work/'graduation-thesis-materials/graduation-manuscript'
            (manuscript/'docs').mkdir(parents=True); (manuscript/'assets').mkdir()
            with patch.object(publish.exp, 'WORK', work), patch.object(publish.full, 'OUT', out):
                publish.main()
            text = (manuscript/'docs/chap02_objective_results.tex').read_text(encoding='utf8')
            self.assertIn('4472', text)
            self.assertIn('潜在材料暴露', text)
            self.assertTrue((manuscript/'assets/objective_main_accuracy.pdf').is_file())
