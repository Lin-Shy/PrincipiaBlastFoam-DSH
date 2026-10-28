import json
import unittest
import terra_stream as s


def event(x):return 'data: '+json.dumps(x,ensure_ascii=False)+'\n\n'


class StreamIntegrityTests(unittest.TestCase):
    def stream(self):
        return ''.join([event(dict(id='r1',model='gpt-6.1-terra',choices=[dict(index=0,delta=dict(content='{"中文":'),finish_reason=None)])),event(dict(id='r1',model='gpt-6.1-terra',choices=[dict(index=0,delta=dict(content='1}'),finish_reason='stop')])),event(dict(id='r1',model='gpt-6.1-terra',choices=[],usage=dict(prompt_tokens=10,completion_tokens=4))), 'data: [DONE]\n\n'])

    def test_reconstruct_unicode_and_final_usage(self):
        r=s.normalize(self.stream(),['gpt-6.1-terra'])
        self.assertEqual(json.loads(r['choices'][0]['message']['content']),{'中文':1})
        self.assertEqual(r['usage']['completion_tokens'],4)

    def test_missing_done_is_not_success(self):
        with self.assertRaisesRegex(ValueError,'incomplete'):s.normalize(self.stream().replace('data: [DONE]\n\n',''),['gpt-6.1-terra'])

    def test_wrong_model_is_not_relabelled(self):
        with self.assertRaisesRegex(ValueError,'model_identity_mismatch'):s.normalize(self.stream().replace('gpt-6.1-terra','gpt-6-sol'),['gpt-6.1-terra'])

    def test_usage_is_never_estimated(self):
        x=self.stream();x=x.replace(event(dict(id='r1',model='gpt-6.1-terra',choices=[],usage=dict(prompt_tokens=10,completion_tokens=4))),'')
        with self.assertRaisesRegex(ValueError,'usage_unknown'):s.normalize(x,['gpt-6.1-terra'])

    def test_candidate_changes_no_scoring_input(self):
        import terra_candidate as c
        item=c.controls()[0];p,req,count=s.request(item,'medium');_,old,_=s.terra.request('gpt_sol',item)
        self.assertEqual(req['body']['messages'],old['body']['messages'])
        self.assertEqual(req['body']['response_format'],old['body']['response_format'])
        self.assertLessEqual(count+req['body']['max_completion_tokens'],32768)
        self.assertTrue(p['stream'])

    def test_explicit_overload_before_answer_is_distinguished(self):
        raw=event(dict(model='gpt-6.1-terra',choices=[dict(delta=dict(role='assistant'))]))+event(dict(error=dict(type='upstream_error',message='Servers overloaded')))
        self.assertIsNotNone(s.rejection(raw))
        partial=event(dict(model='gpt-6.1-terra',choices=[dict(delta=dict(content='partial'))]))+event(dict(error=dict(type='upstream_error',message='Servers overloaded')))
        self.assertIsNone(s.rejection(partial))


if __name__=='__main__':unittest.main()
