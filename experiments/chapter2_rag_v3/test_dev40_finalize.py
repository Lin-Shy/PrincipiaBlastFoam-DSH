import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import dev40_finalize as f


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.root=Path(self.tmp.name)/'sample'
        self.root.mkdir()
        self.req={'body':{'model':'fixed'},'url':'https://example.invalid/v1'}
        self.item={'sample_id':'sample'}
        self.profile={'protocol':'chat_completions'}
        self.patch=patch.object(f,'request',return_value=(self.profile,self.req,100))
        self.patch.start()

    def tearDown(self):
        self.patch.stop();self.tmp.cleanup()

    def save_request(self,p):
        f.s.save(p/'request.json',{'request':self.req})

    def test_502_is_retryable_without_overwriting_original(self):
        self.save_request(self.root)
        f.s.save(self.root/'status.json',{'reason':'http_502','status':'failed'})
        (self.root/'response.txt').write_text('<html>502</html>')
        before=f.s.sha(self.root/'response.txt')
        with patch.object(f.core,'parse_current',side_effect=ValueError('bad JSON')):
            self.assertEqual(f.reconcile(self.root,'gpt_sol',self.item),'pending')
        self.assertEqual(f.s.sha(self.root/'response.txt'),before)

    def test_timeout_with_request_but_no_response_is_held(self):
        self.save_request(self.root)
        f.s.save(self.root/'status.json',{'status':'failed','reason':'timed out'})
        self.assertEqual(f.reconcile(self.root,'gpt_sol',self.item),'unknown_hold')

    def test_valid_recovery_is_canonical_and_never_sent_twice(self):
        self.save_request(self.root)
        (self.root/'response.txt').write_text('502')
        f.s.save(self.root/'status.json',{'reason':'http_502'})
        recovered=self.root/'recovery/attempt_1'
        self.save_request(recovered)
        f.s.save(recovered/'response.txt',{'choices':[]})
        expected={'record':{'K':1},'usage':{}}
        def parse(profile,raw,item):
            if raw==502:raise ValueError('invalid response')
            return expected
        with patch.object(f.core,'parse_current',side_effect=parse):
            self.assertEqual(f.reconcile(self.root,'gpt_sol',self.item),'valid')
            self.assertEqual(f.reconcile(self.root,'gpt_sol',self.item),'valid')
        self.assertEqual(f.s.load(self.root/'parsed.json'),expected)
        self.assertEqual((self.root/'response.txt').read_text(),'502')

    def test_request_drift_fails_before_resend(self):
        f.s.save(self.root/'request.json',{'request':{'body':'changed'}})
        with self.assertRaisesRegex(ValueError,'request drift'):
            f.reconcile(self.root,'gpt_sol',self.item)

    def test_finite_attempt_budget(self):
        for n in range(1,4):
            p=self.root/'recovery'/('attempt_'+str(n));self.save_request(p)
            (p/'response.txt').write_text('502')
            f.s.save(p/'status.json',{'http_status':502})
        with patch.object(f.core,'parse_current',side_effect=ValueError('bad')):
            self.assertEqual(f.reconcile(self.root,'gpt_sol',self.item),'attempt_limit')


if __name__=='__main__':unittest.main()
