import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import objective_sync_materials as sync

class MaterialSyncTests(unittest.TestCase):
    def test_closed_snapshot_update_and_repeat_guard(self):
        e=sync.exp
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2]/'.local') as tmp:
            root=Path(tmp);out=root/'experiment';docs=root/'graduation-thesis-materials/graduation-manuscript/docs';research=root/'graduation-thesis-materials/graduation-research'
            docs.mkdir(parents=True);(research/'chapters').mkdir(parents=True);(out/'results').mkdir(parents=True);(out/'supplementary_parser/results').mkdir(parents=True)
            files={'chap02.tex':r'\input{docs/chap02_knowledge_qa_results.tex}',
                   'abstract.tex':'\n14B完整图自主模式的算术与几何EAS\nWith 14B, full-graph Agentic arithmetic/geometric EAS',
                   'chap05.tex':'其次，既有blastFoam仿真工作流','appendix_ch02.tex':r'\section{正式运行与来源绑定}'}
            for name,text in files.items():(docs/name).write_text(text,encoding='utf8')
            for p in (research/'README.md',research/'OVERVIEW.md',research/'chapters/chapter02.md'):p.write_text('# existing\nprior content\n',encoding='utf8')
            s={'status':'closed','planned':4472,'configurations':[{'model':'qwen3-8b','method':'graph','accuracy':.2},{'model':'qwen3-14b','method':'graph','accuracy':.3}]}
            a=out/'results/snapshot.json';b=out/'supplementary_parser/results/snapshot.json';a.write_text(json.dumps(s),encoding='utf8');b.write_text('{"status":"closed"}',encoding='utf8')
            (out/'results/statistics_audit.json').write_text(json.dumps({'status':'passed','outputs':[{'snapshot_sha256':e.sha(a)},{'snapshot_sha256':e.sha(b)}]}),encoding='utf8')
            with patch.object(e,'WORK',root),patch.object(e,'OUT',out):
                sync.main()
                self.assertIn('20.00\\%',(docs/'abstract.tex').read_text(encoding='utf8'))
                self.assertIn('prior content',(research/'README.md').read_text(encoding='utf8'))
                with self.assertRaises(ValueError):sync.main()
if __name__=='__main__':unittest.main()
