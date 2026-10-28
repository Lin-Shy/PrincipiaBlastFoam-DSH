from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase,main
from unittest.mock import patch
import terra_validation as v


class AcceptanceBoundaryTests(TestCase):
    @classmethod
    def setUpClass(cls):cls.protocol,cls.data=v.inputs()

    def evaluate(self,transform=lambda phase,labels:labels):
        def labels(phase,packet):
            x=deepcopy(self.data[phase][1]['human'])
            for r in x.values():r['judge_id']='gpt_sol'
            return transform(phase,x)
        with TemporaryDirectory() as d,patch.object(v,'ROOT',Path(d)),patch.object(v,'collect',side_effect=labels):
            return v.report()

    def test_perfect_reference_passes_target_gate(self):
        r=self.evaluate()
        self.assertTrue(r['accepted'])
        self.assertFalse(r['unseen_independent_audit'])
        self.assertFalse(r['full_sol_replacement_completed'])

    def test_one_missing_prevents_pass(self):
        def omit(phase,x):
            if phase=='audit':x.pop(next(iter(x)))
            return x
        r=self.evaluate(omit)
        self.assertFalse(r['accepted']);self.assertEqual(r['decision'],'pending_missing_or_unknown')

    def test_perfect_knowledge_cannot_override_eas_error(self):
        def corrupt(phase,x):
            if phase=='audit':
                for r in x.values():r['fact_gate']=0
            return x
        r=self.evaluate(corrupt)
        self.assertFalse(r['accepted']);self.assertIn('EAS_arith:MAE',r['failed_gates'])


if __name__=='__main__':main()
