import unittest
from unittest.mock import patch
from pathlib import Path
from objective_scoring import score
from objective_statistics import holm
class ScoringTests(unittest.TestCase):
    def check(self,kind,answer,gold='pRef',**kwargs):
        return score(dict(id='fixture',type=kind),dict(answer=gold,**kwargs),dict(status='answered',answer=answer))
    def test_explicit_answer_not_explanation(self):
        self.assertEqual(self.check('fill','说明提到pRef\nFINAL: pName')['score'],0)
        self.assertEqual(self.check('fill','说明\nFINAL: pRef')['score'],1)
    def test_conflicts(self):
        for s in ('FINAL: A\nFINAL: B','FINAL: A或B','答案A'):
            self.assertFalse(self.check('single',s,'A')['format_valid'])
    def test_numeric(self):
        self.assertEqual(self.check('short','FINAL: 0.001','1e-3',numeric=True,relative_tolerance=1e-9)['score'],1)
        for s in ('NaN','Infinity','0.001秒','1e-2'):
            self.assertEqual(self.check('short','FINAL: '+s,'1e-3',numeric=True,relative_tolerance=1e-9)['score'],0)
    def test_case_sensitive(self):
        self.assertEqual(self.check('fill','FINAL: pref')['score'],0)
    def test_alias(self):
        self.assertEqual(self.check('fill','FINAL: alias',aliases=['alias'])['score'],1)
        self.assertEqual(self.check('judge','FINAL: false','错误')['score'],1)
    def test_failure(self):
        self.assertEqual(score(dict(id='x',type='fill'),dict(answer='x'),dict(status='transport_error',answer='FINAL: x'))['score'],0)
    def test_holm(self):
        self.assertEqual(holm([.01,.04,.03]),[.03,.06,.06])
    def test_supercomputer_response_preserves_physical_identity(self):
        import objective_experiment as experiment
        raw={'model':'Qwen3-8B','usage':{'prompt_tokens':3,'completion_tokens':2},'choices':[]}
        with patch('chapter2_qwen_routing.routed_client',return_value=lambda body,turn:{'status':'response','raw_response':raw}):
            result=experiment.supercomputer_client(Path('unused'))({'max_tokens':8},0)
        self.assertEqual(result['response']['model'],'qwen3-8b')
        self.assertEqual(result['raw_response']['model'],'Qwen3-8B')
        with patch('chapter2_qwen_routing.routed_client',return_value=lambda body,turn:{'status':'model_mismatch'}):
            self.assertEqual(experiment.supercomputer_client(Path('unused'))({'max_tokens':8},0)['status'],'model_identity_mismatch')
if __name__=='__main__':unittest.main()
