import unittest
from unittest.mock import patch
import test160_runner as runner
import test160_evaluation as evaluation


class TestPreparationTests(unittest.TestCase):
    def test_generation_rejects_unconfirmed_matrix_before_runtime(self):
        with patch.object(runner,'runtime') as runtime:
            with self.assertRaises(PermissionError):runner.execute(None)
            runtime.assert_not_called()

    def test_evaluation_rejects_unconfirmed_matrix_before_gold_or_results(self):
        with patch.object(evaluation.s,'load') as load:
            with self.assertRaises(PermissionError):evaluation.packet(None)
            load.assert_not_called()

    def test_supplement_generation_requires_confirmation_before_runtime(self):
        with patch.object(runner,'runtime') as runtime:
            with self.assertRaises(PermissionError):runner.execute_single_pass(None)
            runtime.assert_not_called()

    def test_supplement_cannot_use_main_only_confirmation(self):
        with patch.object(evaluation.s,'load',return_value={'owner_confirmed':True,'manifest_sha256':'current'}),patch.object(evaluation.s,'sha',return_value='current'):
            with self.assertRaises(PermissionError):evaluation.authorize('confirmation.json','single_pass')

    def test_stale_confirmation_is_rejected(self):
        with patch.object(evaluation.s,'load',return_value={'owner_confirmed':True,'manifest_sha256':'old'}),patch.object(evaluation.s,'sha',return_value='current'):
            with self.assertRaises(PermissionError):evaluation.authorize('confirmation.json')


if __name__=='__main__':unittest.main()
