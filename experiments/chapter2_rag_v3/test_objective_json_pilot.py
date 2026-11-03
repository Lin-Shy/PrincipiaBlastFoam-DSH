import unittest
from objective_json_pilot import score


class JsonAnswerTests(unittest.TestCase):
    def result(self, answer, action_answer=None):
        return {'status': 'answered', 'answer': answer, 'turns': [{'action': {
            'action': 'final', 'answer': answer if action_answer is None else action_answer,
            'references': []}}]}

    def test_choice_and_conflicting_or_multiline_answer(self):
        q, gold = {'id': 'x', 'type': 'single'}, {'answer': 'A'}
        self.assertEqual(score(q, gold, self.result('A'))['score'], 1)
        self.assertFalse(score(q, gold, self.result('A\nB'))['format_valid'])
        self.assertFalse(score(q, gold, self.result('A', 'B'))['format_valid'])
        self.assertFalse(score(q, gold, self.result('A or B'))['format_valid'])

    def test_alias_numeric_and_failure(self):
        q = {'id': 'x', 'type': 'fill'}
        self.assertEqual(score(q, {'answer': 'foo', 'aliases': ['bar']}, self.result('bar'))['score'], 1)
        gold = {'answer': '1', 'numeric': True, 'absolute_tolerance': '0.1'}
        self.assertEqual(score(q, gold, self.result('1.1'))['score'], 1)
        self.assertEqual(score(q, gold, self.result('1.101'))['score'], 0)
        self.assertFalse(score(q, gold, self.result(''))['format_valid'])
        self.assertEqual(score(q, gold, {'status': 'invalid_action'})['score'], 0)


if __name__ == '__main__':
    unittest.main()
