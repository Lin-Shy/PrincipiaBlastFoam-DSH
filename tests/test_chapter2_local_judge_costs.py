import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments/retrieval_method'))
from chapter2_local_judge_costs import physical_local_cost


class CostTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        body={'model':'Qwen3-14B'}
        self.record=dict(provider='qwen_local',transport_attempts=1,status='response',
            started_utc='2026-10-15T00:00:00+00:00',request=body,
            request_sha256=hashlib.sha256(json.dumps(body,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest(),
            endpoint='http://localhost:8001/v1/chat/completions',seconds=2,
            raw_response=dict(usage=dict(prompt_tokens=100,completion_tokens=20)))
    def write(self,name,**changes):
        p=self.root/name;p.write_text(json.dumps({**self.record,**changes}),encoding='utf-8');return p
    def test_copies_deduplicate_physical_attempt(self):
        a=self.write('a.json');b=self.write('b.json');r=physical_local_cost([a,a,b])
        self.assertEqual(r['physical_attempts'],1);self.assertEqual(r['known_total_tokens'],120)
        self.assertEqual(r['duplicate_physical_events_not_recharged'],1);self.assertEqual(r['sum_physical_request_seconds'],2)
    def test_failed_usage_unknown_not_free(self):
        p=self.write('failed.json',status='transport_error',raw_response=None)
        r=physical_local_cost([p]);self.assertEqual(r['usage_unknown_attempts'],1);self.assertIsNone(r['money_cost'])
    def test_in_flight_rejected(self):
        with self.assertRaises(ValueError):physical_local_cost([self.write('live.json',status='in_flight')])
    def test_conflicting_copy_rejected(self):
        with self.assertRaises(ValueError):physical_local_cost([self.write('a.json'),self.write('b.json',seconds=3)])
    def test_distinct_start_counts_separately(self):
        r=physical_local_cost([self.write('a.json'),self.write('b.json',started_utc='2026-10-15T00:00:01+00:00')])
        self.assertEqual(r['physical_attempts'],2);self.assertEqual(r['known_total_tokens'],240)
    def test_fingerprint_and_boolean_usage(self):
        with self.assertRaises(ValueError):physical_local_cost([self.write('a.json',request_sha256='bad')])
        r=physical_local_cost([self.write('b.json',raw_response=dict(usage=dict(prompt_tokens=True,completion_tokens=20)))])
        self.assertEqual(r['usage_unknown_attempts'],1)


if __name__=='__main__':unittest.main()
