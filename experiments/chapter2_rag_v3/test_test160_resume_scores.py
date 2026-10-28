"""Recovery boundary checks without network or credentials."""
import json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
import test160_resume_scores as r

class RecoveryBoundaries(unittest.TestCase):
    def case(self,code,body,reason=None,response=True):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        root=Path(tmp.name);folder=root/'recovery/attempt_1';folder.mkdir(parents=True)
        req={'body':{'model':'frozen-model','messages':['unchanged']}}
        (folder/'request.json').write_text(json.dumps({'request':req}),encoding='utf-8')
        (folder/'status.json').write_text(json.dumps({'http_status':code,'reason':reason}),encoding='utf-8')
        if response:(folder/'response.txt').write_text(json.dumps(body),encoding='utf-8')
        return root,req
    def test_explicit_billing_rejection_can_recover(self):
        root,req=self.case(403,{'error':{'type':'billing_error'}})
        with patch.object(r.rec,'request',return_value=({},req,1)):
            self.assertTrue(r.eligible(root,'gpt_sol',{'generation_failed':False})[0])
    def test_unanswered_post_is_never_resent(self):
        root,req=self.case(None,{},response=False)
        with patch.object(r.rec,'request',return_value=({},req,1)):
            self.assertFalse(r.eligible(root,'gpt_sol',{'generation_failed':False})[0])
    def test_model_unavailable_is_held(self):
        root,req=self.case(404,{'error':{'type':'invalid_request_error','code':'model_not_found'}})
        with patch.object(r.rec,'request',return_value=({},req,1)):
            self.assertFalse(r.eligible(root,'deepseek_flash',{'generation_failed':False})[0])
            self.assertTrue(r.eligible(root,'deepseek_flash',{'generation_failed':False},retry_rejected_model=True)[0])
    def test_formal_generation_failure_never_scored(self):
        self.assertFalse(r.eligible(Path('unused'),'gpt_sol',{'generation_failed':True})[0])
    def test_valid_record_is_reused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'parsed.json').write_text('{}')
            self.assertFalse(r.eligible(root,'gpt_sol',{'generation_failed':False})[0])
if __name__=='__main__':unittest.main()
