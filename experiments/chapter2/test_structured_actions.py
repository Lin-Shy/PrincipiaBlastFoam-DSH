"""Behavior regressions for bounded queries, compact JSON and lossless strings."""
import json,unittest,tempfile
from pathlib import Path
from types import SimpleNamespace
from structured_actions import bounded_specs,decode,grammar,configure
from runtime import action_schema,run_question
from principia_core.retrieval.knowledge_qa import tool_specs
from models import Client,Deployment,payload,sha

def compact(value):return json.dumps(value,ensure_ascii=False,separators=(',',':'))

class StructuredActionTests(unittest.TestCase):
    def setUp(self):self.schema=action_schema(tool_specs('bm25'),False)

    def test_multiline_presentation_preserves_full_synthetic_protocol(self):
        from interface_repair_checks import definitions,NEWLINES
        from models import EXPERIMENT
        old=json.loads((EXPERIMENT/'technical/compact_actions_20261104/fixtures.json').read_text('utf-8'))
        current=definitions();prior=old['cases']
        self.assertEqual(len(current),12)
        self.assertEqual(sum(len(c['turns']) for c in current),14)
        for before,after in zip(prior,current):
            if before['name']!='newlines':
                self.assertEqual(before,after)
            else:
                self.assertEqual(before['turns'][0]['answer'],after['turns'][0]['answer'])
                self.assertEqual(before['turns'][0]['schema'],after['turns'][0]['schema'])
                prompt=after['turns'][0]['prompt']
                copied=prompt.split('<<<BEGIN_LITERAL_TEXT>>>\n',1)[1].split('\n<<<END_LITERAL_TEXT>>>',1)[0]
                self.assertEqual(copied,NEWLINES)
                self.assertEqual([ord(c) for c in copied if ord(c)<32],[10,9])
        self.assertEqual(old['query_limit'],512)
        self.assertEqual(old['output_tokens'],2048)

    def test_query_boundary_in_unicode_characters(self):
        for n in [1,512]:
            value=dict(action='tool',name='search',arguments=dict(query='密'*n))
            self.assertEqual(decode(compact(value),self.schema),value)
        for text in ['', '密'*513]:
            with self.assertRaises(ValueError):decode(compact(dict(action='tool',name='search',arguments=dict(query=text))),self.schema)

    def test_catalog_empty_query_and_path_independent_limit(self):
        specs=bounded_specs(tool_specs('bm25'));by={s['name']:s['parameters']['properties'] for s in specs}
        self.assertEqual(by['catalog']['query']['minLength'],0)
        self.assertEqual(by['search']['query']['maxLength'],512)
        self.assertEqual(by['read_source']['path']['maxLength'],2000)
        decode(compact(dict(action='tool',name='catalog',arguments=dict(query=''))),self.schema)

    def test_whitespace_in_strings_survives_but_external_whitespace_rejected(self):
        value=dict(action='final',answer='第一行\n  第二行\t末尾',references=[])
        self.assertEqual(decode(compact(value),self.schema),value)
        with self.assertRaises(ValueError):decode(json.dumps(value),self.schema)

    def test_formula_and_quoted_code_roundtrip(self):
        text='functions { #includeFunc "probes"; }\n'+r'\frac{a}{b} + \rho + \beta + \tau'
        value=dict(action='final',answer=text,references=[])
        outer=compact(dict(choices=[dict(message=dict(content=compact(value)))]))
        self.assertEqual(decode(json.loads(outer)['choices'][0]['message']['content'],self.schema)['answer'],text)

    def test_control_characters_never_salvaged(self):
        for text in ['\x0crac{a}{b}','\x08eta']:
            value=dict(action='final',answer=text,references=[])
            for ascii_flag in [True,False]:
                with self.assertRaises(ValueError):decode(json.dumps(value,ensure_ascii=ascii_flag,separators=(',',':')),self.schema)

    def test_objective_and_final_only_schema(self):
        value=dict(action='final',answer='说明',references=[],final_answer='42')
        schema=action_schema([],True,True);self.assertEqual(decode(compact(value),schema),value)
        del value['final_answer']
        with self.assertRaises(ValueError):decode(compact(value),schema)
        with self.assertRaises(ValueError):decode(compact(dict(action='tool',name='search',arguments=dict(query='x'))),schema)

    def test_invalid_structures_and_integer_bool_rejected(self):
        for value in [dict(action='final',answer='x',references=[],extra=1),dict(action='tool',name='read_source',arguments=dict(path='manual/x',start=True,end=2))]:
            with self.assertRaises(ValueError):decode(compact(value),self.schema)
        with self.assertRaises(ValueError):decode('{"action":"final","answer":"x","answer":"y","references":[]}',self.schema)

    def test_server_ignoring_constraints_cannot_execute_long_query(self):
        class Tools:
            method='bm25';available=True;events=[];characters=0;delivered_lines=set()
            def execute(self,*a):raise AssertionError('Overlong action reached tool')
        def complete(body,path):
            self.assertEqual(body['max_tokens'],2048);self.assertIn('structured_outputs',body);self.assertNotIn('response_format',body)
            return dict(status='response',raw_response=dict(model='synthetic',usage=dict(prompt_tokens=100,completion_tokens=100),choices=[dict(finish_reason='stop',message=dict(content=compact(dict(action='tool',name='search',arguments=dict(query='x'*513)))))]))
        r=run_question(dict(question='synthetic'),'agentic','bm25','M',Tools(),SimpleNamespace(complete=complete),SimpleNamespace(logical_model='llama3.1-8b',model='synthetic'),lambda _:100)
        self.assertEqual(r['status'],'invalid_action');self.assertEqual(len(r['turns']),1)

    def test_original_response_bytes_saved_without_headers(self):
        raw=compact(dict(model='synthetic',choices=[dict(message=dict(content=compact(dict(action='final',answer='\\frac{a}{b}',references=[]))))])).encode()
        class Reply:
            status=200
            def __enter__(self):return self
            def __exit__(self,*a):pass
            def read(self):return raw
        d=Deployment('llama3.1-8b','synthetic','http://invalid.example/v1/chat/completions','SECRET_TEST_ONLY')
        c=Client(d);c.opener=SimpleNamespace(open=lambda *a,**k:Reply())
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'00.json';r=c.complete(payload(d,[dict(role='user',content='synthetic')],2048),p)
            self.assertEqual(p.with_suffix('.response.bin').read_bytes(),raw)
            self.assertEqual(r['response_sha256'],sha(raw));self.assertNotIn('SECRET_TEST_ONLY',p.read_text('utf-8'))

    def test_grammar_acceptance_agrees_on_boundaries_and_compactness(self):
        import xgrammar as xgr
        g=xgr.Grammar.from_ebnf(grammar(self.schema));accept=xgr.testing._is_grammar_accept_string
        for n,expected in [(1,True),(512,True),(513,False),(0,False)]:
            value=dict(action='tool',name='search',arguments=dict(query='密'*n))
            self.assertEqual(accept(g,compact(value)),expected)
        value=dict(action='final',answer='functions { includeFunc "probes"; }\n'+r'\frac{a}{b}',references=[])
        self.assertTrue(accept(g,compact(value)));self.assertFalse(accept(g,json.dumps(value)))
        self.assertTrue(accept(g,compact(dict(action='tool',name='catalog',arguments=dict(query='',offset=0)))))

if __name__=='__main__':unittest.main()
