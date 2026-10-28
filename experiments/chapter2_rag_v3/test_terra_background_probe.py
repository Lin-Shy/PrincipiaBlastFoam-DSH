import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import terra_background_probe as b


class BackgroundProbeTests(unittest.TestCase):
    def test_preserves_task_content_and_budget(self):
        item=b.c.controls()[0];profile,req,count=b.request(item)
        _,old,_=b.native.request(item,'medium')
        self.assertEqual(req['body']['input'],old['body']['input'])
        self.assertEqual(req['body']['model'],'gpt-6.1-terra')
        self.assertTrue(req['body']['background']);self.assertFalse(req['body']['store'])
        self.assertLessEqual(count+profile['output_token_cap'],32768)

    def test_receipt_identity_cannot_change(self):
        raw=dict(id='resp_1',model='gpt-6.1-terra',status='queued')
        self.assertEqual(b.response_identity(raw),'resp_1')
        with self.assertRaisesRegex(ValueError,'response_id_changed'):b.response_identity(raw,'resp_2')
        raw['model']='gpt-6-sol'
        with self.assertRaisesRegex(ValueError,'model_identity_mismatch'):b.response_identity(raw)

    def test_foreground_variant_preserves_task_and_omits_background(self):
        import terra_foreground_probe as f
        item=b.c.controls()[0];profile,req,count=f.request(item)
        _,old,_=b.native.request(item,'none')
        self.assertEqual(req['body']['input'],old['body']['input'])
        self.assertNotIn('background',req['body'])
        self.assertEqual(req['body']['reasoning'],{'effort':'none'})
        self.assertFalse(req['body']['stream'])

    def test_existing_unknown_prevents_any_post(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'request.json').write_text('{}')
            with patch.object(b,'ROOT',root),patch.object(b.requests,'Session') as session:
                self.assertEqual(b.probe(True)['state'],'existing_probe_hold_no_new_post')
                session.assert_not_called()


if __name__=='__main__':unittest.main()
