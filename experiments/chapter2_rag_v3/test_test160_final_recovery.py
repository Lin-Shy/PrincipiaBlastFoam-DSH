"""No-network tests of the extra epoch and final-publication boundaries."""
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import test160_extra_recovery as epoch
import test160_final_assets as final


class PublicationBoundary(unittest.TestCase):
    def test_unclosed_audit_cannot_publish_even_when_flag_is_true(self):
        with self.assertRaises(RuntimeError):
            final.closure_guard(dict(generation_tasks=5120,answered=4989,dual_valid=4988,
                                     missing_dual=1,formal_experiment_complete=True))

    def test_closed_audit_requires_expected_matrix(self):
        with self.assertRaises(RuntimeError):
            final.closure_guard(dict(generation_tasks=5121,answered=4989,dual_valid=4989,
                                     missing_dual=0,formal_experiment_complete=True))

    def test_valid_closure(self):
        final.closure_guard(dict(generation_tasks=5120,answered=4989,dual_valid=4989,
                                 missing_dual=0,formal_experiment_complete=True))

    def test_prepare_unclosed_makes_no_snapshot_writes(self):
        with patch.object(final,'read',return_value={'formal_experiment_complete':False}), \
             patch.object(final.s,'save') as save:
            with self.assertRaises(RuntimeError):
                final.prepare()
            save.assert_not_called()


class InputEstimateBoundary(unittest.TestCase):
    def test_unapproved_sample_cannot_bypass_input_estimate(self):
        with patch.object(epoch,'APPROVED',set()), \
             patch.object(epoch,'ORIGINAL_REQUEST',side_effect=ValueError('input exceeds cap')):
            with self.assertRaises(ValueError):
                epoch.request('gpt_sol',dict(sample_id='unapproved'))

    def test_reviewed_hold_preserves_wire_payload_and_profile(self):
        with tempfile.TemporaryDirectory() as folder:
            base=Path(folder);root=base/'supplement/single_pass/scoring/gpt_sol/S'
            root.mkdir(parents=True);(root/'input_hold.json').write_text('{}')
            profile={'input_token_cap':26624,'output_token_cap':6144}
            req={'body':{'model':'gpt-6-sol','messages':[{'role':'user','content':'frozen text'}],
                         'max_completion_tokens':6144}}
            tokenizer=SimpleNamespace(encode=lambda text:SimpleNamespace(ids=range(26700)))
            with patch.object(epoch,'BASE',base),patch.object(epoch,'APPROVED',{('gpt_sol','S')}), \
                 patch.object(epoch,'ORIGINAL_REQUEST',side_effect=ValueError('input exceeds cap')), \
                 patch.object(epoch.old.rec.core,'request_for',return_value=(None,profile,req)), \
                 patch.object(epoch.old.rec.dc,'tokenizer',return_value=tokenizer):
                returned,wire,count=epoch.request('gpt_sol',dict(sample_id='S',sources=['original'],generation_failed=False))
            self.assertEqual(returned,{'input_token_cap':26624,'output_token_cap':6144})
            self.assertEqual(wire['body']['messages'],[{'role':'user','content':'frozen text'}])
            self.assertEqual(wire['body']['max_completion_tokens'],8192)
            self.assertEqual(count,26700)


if __name__=='__main__':
    unittest.main()
