import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import test160_terra as t


class ModelAmendmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.item=t.s.load(t.BASE/'scoring/packet.json')['items'][0]['item']

    def test_exact_model_only_wire_delta(self):
        oldp, old, _=t.LEGACY_REQUEST('gpt_sol',self.item)
        p,new,_=t.request('gpt_sol',self.item)
        body=dict(new['body']);body['model']=old['body']['model']
        self.assertEqual(body,old['body'])
        self.assertEqual(p['allowed_response_model_ids'],['gpt-6.1-terra'])
        saved=dict(request=new,profile=p,request_sha256=t.digest(new['body']),packet_item_sha256=t.digest(self.item))
        t.check_request(saved,self.item)
        saved['request']['body']['messages'][0]['content']+=' changed'
        with self.assertRaises(AssertionError):t.check_request(saved,self.item)

    def test_unknown_request_never_resent(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);a=root/'recovery/attempt_1';a.mkdir(parents=True)
            t.s.save(a/'request.json',{})
            with patch.object(t,'check_request'):
                self.assertEqual(t.inspect(root,dict(generation_failed=False)),(False,'transport_unknown_no_resend'))

    def test_existing_score_is_byte_preserved(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=root/'parsed.json';p.write_bytes(b'{"response_model":"gpt-6-sol"}')
            before=p.read_bytes()
            self.assertEqual(t.inspect(root,dict(generation_failed=False)),(False,'reuse_valid'))
            self.assertEqual(before,p.read_bytes())

    def test_failed_generation_never_sent(self):
        self.assertEqual(t.inspect(Path('unused'),dict(generation_failed=True)),(False,'formal_generation_failure'))

    def test_sol_response_rejected_for_terra_request(self):
        profile,_,_=t.request('gpt_sol',self.item)
        raw=dict(model='gpt-6-sol',usage=dict(prompt_tokens=1,completion_tokens=1))
        with self.assertRaisesRegex(ValueError,'model_identity_mismatch'):
            t.scoring.parse_current(profile,raw,self.item)


if __name__=='__main__':unittest.main()
