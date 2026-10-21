import copy,json,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments/retrieval_method'))
from chapter2_qwen_compact_grammar import compact_schema_grammar,compact_grammar_requests
from chapter2_qwen_hard_nonthinking import hard_nonthinking_requests

class CompactGrammarTests(unittest.TestCase):
    def request(self):
        return [dict(stage='source_free_coverage',body=dict(model='qwen3-14b',enable_thinking=False,
            messages=[dict(role='user',content=json.dumps(dict(premise_segments=[dict(id='A1'),dict(id='A2')],hypothesis='claim')))],
            temperature=0,max_tokens=4096))]
    def test_preserves_input_and_decoding_budgets(self):
        original=self.request();snapshot=copy.deepcopy(original)
        expected=hard_nonthinking_requests(original);actual=compact_grammar_requests(original)
        self.assertEqual(original,snapshot)
        expected[0]['body'].pop('response_format');actual[0]['body'].pop('structured_outputs')
        self.assertEqual(actual,expected)
    def test_all_semantic_choices_retained_in_literals(self):
        grammar=compact_grammar_requests(self.request())[0]['body']['structured_outputs']['grammar']
        for value in ['full','partial','missing','wrong','unknown','A1','A2']:
            self.assertIn(json.dumps(json.dumps(value)),grammar)
        self.assertNotIn('A999',grammar)
    def test_field_boundaries_have_only_fixed_literals(self):
        grammar=compact_grammar_requests(self.request())[0]['body']['structured_outputs']['grammar']
        lines=grammar.splitlines()
        self.assertTrue(lines[0].startswith('root ::= n'))
        for line in lines:
            if line.startswith('n'):
                self.assertNotIn('json-char',line)
                self.assertNotIn(r'\s',line)
                self.assertNotIn(r'[ \t',line)
    def test_unsupported_open_objects_rejected(self):
        with self.assertRaises(ValueError):compact_schema_grammar(dict(type='object',properties={},required=[],additionalProperties=True))
        with self.assertRaises(ValueError):compact_schema_grammar(dict(type='integer'))
    def test_fixed_array_enforces_actual_order(self):
        schema=dict(type='array',prefixItems=[dict(type='string',const='A1'),dict(type='string',const='A2')],minItems=2,maxItems=2)
        grammar=compact_schema_grammar(schema)
        self.assertIn('n0 ::= "[" n1 "," n2 "]"',grammar)
        self.assertNotIn('json-char*',grammar.split('n0 ::=')[1].splitlines()[0])

if __name__=='__main__':unittest.main()
