import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import terra_foreground as f


class ForegroundValidationTests(unittest.TestCase):
    def test_positive_probe_is_reused_with_raw_verification(self):
        item=f.c.controls()[0]
        actual=f.verify(f.PROBE_ROOT,item,'none')
        self.assertEqual(actual['response_model'],'gpt-6.1-terra')
        self.assertEqual(actual['record']['fact_gate'],1)
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(f.c,'ROOT',Path(tmp)):
                result=f.collect('controls','none',[item])
                self.assertEqual(result[item['sample_id']],actual['record'])
                self.assertTrue((Path(tmp)/'control_reuse.json').exists())

    def test_only_predeclared_effort_can_execute(self):
        with self.assertRaises(ValueError):f.request(f.c.controls()[0],'high')


if __name__=='__main__':unittest.main()
