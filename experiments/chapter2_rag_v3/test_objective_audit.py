"""Behavioral checks of score reconstruction and closure gating."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import objective_audit as audit
import objective_supplementary_audit as supplementary
from objective_scoring import score

def put(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value),encoding='utf-8')

class ClosureAuditTests(unittest.TestCase):
    def test_closure_reconstructs_and_detects_tampering(self):
        with TemporaryDirectory(dir=Path(__file__).resolve().parents[2]/'.local') as tmp:
            root=Path(tmp); data=root/'data'; out=root/'out'; manifest=root/'manifest.json'
            put(manifest,{'id':'frozen'})
            q={'id':'Q1','type':'single','question':'q','options':{'A':'yes','B':'no','C':'x','D':'y'}}
            g={'id':'Q1','answer':'A','aliases':[]}
            put(data/'model/questions.json',[q]);put(data/'scoring/annotations.json',[g])
            result={'status':'answered','answer':'FINAL: A','manifest_sha256':audit.experiment.sha(manifest)}
            put(out/'generation/cfg/Q1/result.json',result)
            item=score(q,g,result);item['config_id']='cfg'
            put(out/'scores/per_answer.json',[item])
            put(out/'results/snapshot.json',{'status':'closed','completed':1,'configurations':[{'config_id':'cfg','accuracy':1.0}]})
            m={'tasks':1,'configurations':[{'config_id':'cfg'}]}
            with patch.object(audit.experiment,'DATA',data),patch.object(audit.experiment,'OUT',out),patch.object(audit.experiment,'MANIFEST',manifest),patch.object(audit.experiment,'verify',return_value=m):
                audit.main()
                self.assertEqual(audit.experiment.read(out/'results/closure_audit.json')['status'],'passed')
                item['score']=0;put(out/'scores/per_answer.json',[item])
                with self.assertRaises(SystemExit):audit.main()
                self.assertEqual(audit.experiment.read(out/'results/closure_audit.json')['status'],'failed')

    def test_incomplete_snapshot_rejected(self):
        with TemporaryDirectory(dir=Path(__file__).resolve().parents[2]/'.local') as tmp:
            root=Path(tmp);data=root/'data';out=root/'out'
            put(data/'model/questions.json',[]);put(data/'scoring/annotations.json',[])
            put(out/'scores/per_answer.json',[]);put(out/'results/snapshot.json',{'status':'in_progress','completed':0})
            with patch.object(audit.experiment,'DATA',data),patch.object(audit.experiment,'OUT',out),patch.object(audit.experiment,'verify',return_value={'tasks':1}):
                with self.assertRaisesRegex(ValueError,'closed complete'):audit.main()

    def test_supplementary_reconstructs_bare_line_and_strict_link(self):
        from objective_scoring_relaxed import score as relaxed_score
        with TemporaryDirectory(dir=Path(__file__).resolve().parents[2]/'.local') as tmp:
            root=Path(tmp);data=root/'data';out=root/'out';supp=out/'supplementary_parser'
            q={'id':'Q1','type':'single','question':'q'};g={'id':'Q1','answer':'A'}
            result={'status':'answered','answer':'A'}
            put(data/'model/questions.json',[q]);put(data/'scoring/annotations.json',[g])
            put(out/'generation/cfg/Q1/result.json',result)
            original=score(q,g,result);original['config_id']='cfg';put(out/'scores/per_answer.json',[original])
            revised=relaxed_score(q,g,result);revised.update(config_id='cfg',strict_score=original['score'],strict_reason=original['reason'])
            put(supp/'scores/per_answer.json',[revised]);put(supp/'results/snapshot.json',{'status':'closed','completed':1,'source_strict_sha256':audit.experiment.sha(out/'scores/per_answer.json'),'configurations':[{'config_id':'cfg','accuracy':1.0}]})
            with patch.object(audit.experiment,'DATA',data),patch.object(audit.experiment,'OUT',out),patch.object(audit.experiment,'verify',return_value={'tasks':1,'configurations':[{'config_id':'cfg'}]}):
                supplementary.main()
                self.assertEqual(audit.experiment.read(supp/'results/closure_audit.json')['status'],'passed')
                revised['strict_score']=1;put(supp/'scores/per_answer.json',[revised])
                with self.assertRaises(SystemExit):supplementary.main()

if __name__=='__main__':unittest.main()
