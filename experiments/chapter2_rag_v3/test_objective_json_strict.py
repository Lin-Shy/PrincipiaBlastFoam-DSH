import unittest
from objective_json_strict import score


class StrictJsonTests(unittest.TestCase):
    def test_duplicate_answer_rejected(self):
        action = {'action': 'final', 'answer': 'A', 'references': []}
        result = {'status': 'answered', 'answer': 'A', 'turns': [{'action': action,
            'response': {'response': {'choices': [{'message': {'content':
                '{"action":"final","answer":"B","answer":"A","references":[]}'}}]}}}]}
        row = score({'id': 'x', 'type': 'single'}, {'answer': 'A'}, result)
        self.assertEqual(row['score'], 0)
        self.assertEqual(row['reason'], 'invalid_or_duplicate_json')

    def test_valid_action_accepted(self):
        action = {'action': 'final', 'answer': 'A', 'references': []}
        result = {'status': 'answered', 'answer': 'A', 'turns': [{'action': action,
            'response': {'response': {'choices': [{'message': {'content':
                '{"action":"final","answer":"A","references":[]}'}}]}}}]}
        self.assertEqual(score({'id': 'x', 'type': 'single'}, {'answer': 'A'}, result)['score'], 1)
