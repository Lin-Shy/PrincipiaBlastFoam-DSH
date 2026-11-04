"""Synthetic tests only; no calls and no changes to real human labels."""
import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import judge_calibration as jc
from judge_contract import calculate, schema, VERSION
from judge_api_adapter import build, parse
from models import encoded


class CalibrationTests(unittest.TestCase):
    def test_judge_cap_is_separate_from_answer_generation(self):
        with patch.object(jc, 'central_profile', return_value={'output_token_cap': 2048, 'input_token_cap': 30720}):
            p = jc.calibration_profile('gpt_sol', 8192)
            self.assertEqual(p['output_token_cap'], 8192)
            self.assertEqual(p['output_token_cap']+p['input_token_cap'], 32768)
            with self.assertRaises(ValueError): jc.calibration_profile('gpt_sol', 4096)

    def test_payload_allowlist_and_complete_scoring_basis(self):
        p = dict(sample_id='synthetic', question='q', answer='a', generation_failed=False,
                 conditional=False, criteria=[dict(criterion_id='K1', claim='c')], sources=[],
                 applicability='scope', acceptable_answer_range='equivalent', critical_errors=['x'],
                 human_scores={'F': 1}, model='hidden', other_judge={'F': 0})
        q = jc.packet_for(p)
        profile = dict(judge_id='gpt_sol', model_id='synthetic', protocol='chat_completions',
                       output_token_cap=2048, base_url='https://invalid.example/v1', key_env='SYNTHETIC',
                       wire_parameters={}, prompt_version='test')
        body = build(profile, q, 'joint', 'rubric', schema())['body']
        self.assertNotIn('human_scores', str(body)); self.assertNotIn('other_judge', str(body))
        self.assertIn('scope', body['messages'][1]['content'])
        with self.assertRaises(ValueError): build(profile, dict(q, human_scores={}), 'joint', '', schema())

    def test_dual_is_mean_after_nonlinear_EAS(self):
        a = calculate([1], 0, 'not_applicable', False)
        b = calculate([0], 1, 'not_applicable', False)
        m = jc.mean_metrics(a, b)
        self.assertEqual(m['EAS_geo'], 0)
        self.assertEqual(m['EAS_arith'], 50)
        self.assertEqual(m['K'], .5)

    def test_unknown_not_zero_or_dropped_from_full_denominator(self):
        h = calculate([1], 'unknown', 'not_applicable', False)
        a = calculate([1], 1, 'not_applicable', False)
        b = calculate([1], .5, 'not_applicable', False)
        rows = [dict(question_id='q1', generation_failed=False, conditional=False, human=h,
                     gpt_sol=a, deepseek_flash=b, dual_mean=jc.mean_metrics(a, b))]
        z = jc.comparison(rows, 'dual_mean', 'EAS_arith')
        self.assertEqual(z['identified_pairs'], 0); self.assertEqual(z['full_denominator'], 1)
        self.assertIsNone(z['mae']); self.assertEqual(z['fixed_denominator_mae_bounds'], [0, 37.5])
        self.assertEqual(z['fixed_denominator_bias_bounds'], [-12.5, 37.5])

    def test_mean_F_unknown_has_bounds(self):
        h = calculate([1], 1, 'not_applicable', False)
        a = calculate([1], 'unknown', 'not_applicable', False)
        m = jc.mean_metrics(a, h)
        row = dict(question_id='q', generation_failed=False, conditional=False, human=h, dual_mean=m)
        r = jc.comparison([row], 'dual_mean', 'F')
        self.assertEqual(r['fixed_denominator_mae_bounds'], [0, .5])

    def test_generation_failure_has_zero_without_model_call(self):
        p = dict(schema_version=VERSION, sample_id='synthetic', conditional=True,
                 generation_failed=True, criteria=[dict(criterion_id='K1')])
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(jc, 'check_authorized'), patch.object(jc, 'now', return_value='test'):
                class NeverCall:
                    def complete(self, *args): raise AssertionError('Unexpected API call')
                result = jc.run_one('hash', {}, Path(folder), p, 'gpt_sol', {'prompt_version': 'test'}, NeverCall())
                self.assertEqual(result, 'complete')
                r = jc.read(Path(folder)/'gpt_sol/synthetic/result.json')
                self.assertEqual(r['metrics']['EAS_arith'], 0)
                self.assertFalse((Path(folder)/'gpt_sol/synthetic/requests').exists())

    def test_authorization_rejects_acceptance_and_foreign_sample(self):
        a = dict(authorized=True, protocol_sha256='h', phase='calibration', judges=['gpt_sol'],
                 sample_ids=['synthetic'], acceptance_authorized=False, full_generation_authorized=False)
        with patch.object(jc, 'read', return_value=a):
            jc.check_authorized('h', 'gpt_sol', 'synthetic')
            with self.assertRaises(PermissionError): jc.check_authorized('h', 'gpt_sol', 'acceptance')
            with self.assertRaises(PermissionError): jc.check_authorized('different', 'gpt_sol', 'synthetic')
            a['acceptance_authorized'] = True
            with self.assertRaises(PermissionError): jc.check_authorized('h', 'gpt_sol', 'synthetic')

    def test_K_average_and_mean_judge_scores_need_not_be_five_levels(self):
        h = calculate([1, .5, 0], .75, 'not_applicable', False)
        a = calculate([1, .75, 0], 1, 'not_applicable', False)
        row = dict(question_id='q', generation_failed=False, conditional=False, human=h, gpt_sol=a)
        r = jc.comparison([row], 'gpt_sol', 'K')
        self.assertEqual(r['identified_pairs'], 1)
        self.assertAlmostEqual(r['mae'], 1/12)
        self.assertEqual(r['within_025_rate'], 1)


if __name__ == '__main__': unittest.main()
