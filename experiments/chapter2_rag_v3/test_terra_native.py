import json
import unittest
import terra_native as n
from test_terra_stream import event


class NativeIntegrityTests(unittest.TestCase):
    def test_completed_is_authoritative_not_deltas(self):
        r=dict(id='r1',model='gpt-6.1-terra',status='completed',output=[],usage=dict(input_tokens=1,output_tokens=1))
        raw=event(dict(type='response.created',response=dict(id='r1',model='gpt-6.1-terra')))+event(dict(type='response.completed',response=r))
        self.assertEqual(n.normalize(raw,['gpt-6.1-terra']),r)
        with self.assertRaisesRegex(ValueError,'incomplete'):n.normalize(raw.split('data: ')[0],['gpt-6.1-terra'])

    def test_native_envelope_keeps_task_content(self):
        import terra_candidate as c
        item=c.controls()[0];_,old,_=n.CHAT_REQUEST(item,'medium');profile,req,count=n.request(item,'medium')
        self.assertEqual(old['body']['messages'],req['body']['input'])
        self.assertEqual(profile['protocol'],'responses')
        self.assertEqual(req['body']['reasoning'],{'effort':'medium'})
        self.assertLessEqual(count+req['body']['max_output_tokens'],32768)


if __name__=='__main__':unittest.main()
