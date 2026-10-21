import copy,json,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments/retrieval_method'))
from chapter2_qwen_hard_nonthinking import hard_nonthinking_requests
from chapter2_qwen_structured_output import constrain_requests

class HardModeTests(unittest.TestCase):
    def request(self):
        return [dict(stage='source_free_coverage',body=dict(model='qwen3-14b',enable_thinking=False,
            messages=[dict(role='user',content=json.dumps(dict(premise_segments=[dict(id='A1')],hypothesis='claim')))],
            temperature=0,max_tokens=4096))]
    def test_only_explicit_template_override_added(self):
        source=self.request();before=copy.deepcopy(source);expected=constrain_requests(source);result=hard_nonthinking_requests(source)
        self.assertEqual(source,before)
        self.assertEqual(result[0]['body'].pop('chat_template_kwargs'),{'enable_thinking':False})
        self.assertEqual(result,expected)
    def test_conflicting_mode_rejected(self):
        for field,value in [('enable_thinking',True),('chat_template_kwargs',{'enable_thinking':True}),('chat_template_kwargs',{'unknown':False})]:
            source=self.request();source[0]['body'][field]=value
            with self.assertRaises(ValueError):hard_nonthinking_requests(source)
    def test_idempotent_mode_preserves_schema_choices(self):
        once=hard_nonthinking_requests(self.request());self.assertEqual(once,hard_nonthinking_requests(once))
        schema=once[0]['body']['response_format']['json_schema']['schema']
        self.assertIn('unknown',schema['properties']['verdict']['enum']);self.assertIn('wrong',schema['properties']['verdict']['enum'])

if __name__=='__main__':unittest.main()
