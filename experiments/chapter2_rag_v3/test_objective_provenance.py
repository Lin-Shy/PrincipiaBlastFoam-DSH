import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import objective_provenance as provenance

class ProvenanceTests(unittest.TestCase):
    def test_inventory_binds_bytes_without_copying_private_contents(self):
        exp=provenance.exp
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2]/'.local') as tmp:
            root=Path(tmp); manifest=root/'manifest.json'; manifest.write_text('{}')
            files=['results/per_answer.csv','results/summary.csv','scores/per_answer.json',
                   'results/closure_audit.json','supplementary_parser/results/per_answer.csv',
                   'supplementary_parser/results/summary.csv','supplementary_parser/results/closure_audit.json',
                   'analysis/format_pairs.csv']
            for name in files:
                path=root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text('fixture',encoding='utf8')
            (root/'results/snapshot.json').write_text('{"status":"closed"}',encoding='utf8')
            strict_hash=exp.sha(root/'scores/per_answer.json')
            (root/'supplementary_parser/results/snapshot.json').write_text(json.dumps({'status':'closed','source_strict_sha256':strict_hash}),encoding='utf8')
            for section in ('results','supplementary_parser/results'):
                snap=root/section/'snapshot.json'
                (root/section/'closure_audit.json').write_text(json.dumps({'status':'passed','snapshot_sha256':exp.sha(snap)}),encoding='utf8')
            raw=root/'generation/cfg/Q/requests/request.json';raw.parent.mkdir(parents=True)
            raw.write_text('private-fixture-content',encoding='utf8')
            with patch.object(exp,'OUT',root),patch.object(exp,'MANIFEST',manifest):provenance.main()
            inventory=(root/'results/raw_inventory.jsonl').read_text(encoding='utf8')
            record=json.loads(inventory)
            self.assertNotIn('private-fixture-content',inventory)
            self.assertEqual(record['sha256'],exp.sha(raw))
            self.assertEqual(json.loads((root/'results/provenance.json').read_text(encoding='utf8'))['raw_file_count'],1)

if __name__=='__main__':unittest.main()
