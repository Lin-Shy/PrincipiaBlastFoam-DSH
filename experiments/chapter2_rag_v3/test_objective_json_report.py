import sys
import unittest
from unittest.mock import patch
import objective_json_report as report
import objective_json_pilot as pilot
import objective_json_strict as strict


class JsonReportTests(unittest.TestCase):
    def test_adapter_does_not_replace_scorer_used_by_pilot(self):
        original = pilot.rules.score
        def verify():
            from objective_scoring import score
            self.assertIs(score, strict.score)
            self.assertIs(pilot.rules.score, original)
            action = {'action': 'final', 'answer': 'A', 'references': []}
            result = {'status': 'answered', 'answer': 'A', 'turns': [{'action': action,
                'response': {'response': {'choices': [{'message': {'content':
                    '{"action":"final","answer":"A","references":[]}'}}]}}}]}
            self.assertEqual(score({'id': 'x', 'type': 'single'}, {'answer': 'A'}, result)['score'], 1)
        with patch.object(report.full, 'use_full'), patch.object(report.experiment, 'report', verify), \
                patch.object(report.full, 'OUT') as out, patch.dict(sys.modules):
            out.__truediv__.return_value.read_text.return_value = ''
            report.main()
