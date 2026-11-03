import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import objective_review as review

class ReviewPacketTests(unittest.TestCase):
    def test_packet_uses_source_and_detects_drift(self):
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2]/'.local') as tmp:
            root=Path(tmp);source=root/'manual.txt';source.write_text('alpha\nbeta\ngamma\n',encoding='utf8')
            digest=hashlib.sha256(source.read_bytes()).hexdigest()
            question={'id':'Q','question':'fixture'}
            gold={'answer':'beta','aliases':[],'evidence':[{'path':'manual.txt','start':2,'end':2,'sha256':digest}]}
            with patch.object(review,'CORPUS',root):
                packet=review.packet(question,gold)
                self.assertEqual(packet['expected_answer'],'beta')
                self.assertIn('2: beta',packet['sources'][0]['text'])
                source.write_text('changed',encoding='utf8')
                with self.assertRaisesRegex(ValueError,'source hash mismatch'):review.packet(question,gold)

if __name__=='__main__':unittest.main()
