import unittest
from unittest.mock import patch
import terra_candidate as c
import terra_stream as s


class LatencyCandidateTests(unittest.TestCase):
    def test_lower_effort_preserves_scoring_content(self):
        item=c.controls()[0]
        _,original,_=s.terra.request('gpt_sol',item)
        for effort in ('none','low'):
            profile,request,count=s.request(item,effort)
            self.assertEqual(request['body']['messages'],original['body']['messages'])
            self.assertEqual(request['body']['response_format'],original['body']['response_format'])
            self.assertEqual(request['body']['model'],'gpt-6.1-terra')
            self.assertEqual(request['body']['reasoning_effort'],effort)
            self.assertLessEqual(count+profile['output_token_cap'],32768)

    def test_unknown_effort_is_rejected(self):
        with self.assertRaises(ValueError):s.request(c.controls()[0],'unverified')

    def test_existing_uncertain_control_is_held_without_send(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder=root/'controls/none/TC_correct/attempt_1'
            folder.mkdir(parents=True)
            c.stream.terra.s.save(folder/'status.json',{'status':'unknown','post_maybe_sent':True})
            with patch.object(c,'ROOT',root),patch.object(c.stream,'attempt') as send:
                self.assertEqual(c.score('controls','none',c.controls()[0],None),'existing_unknown_or_invalid_hold')
                send.assert_not_called()


if __name__=='__main__':unittest.main()
