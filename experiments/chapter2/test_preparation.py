"""Preparation regressions. Synthetic fixtures never become human labels."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import json,tempfile,unittest
from models import Client,Deployment,encoded,payload,strict_json
from runtime import run_question,tools_for,action_content
from runner import run_one,authorize_dispatch,model_lock
from objective_scoring import score
import human_review as hr

class Tools:
    method='bm25'
    def __init__(self):self.events=[];self.characters=0;self.delivered_lines=set()
    @property
    def available(self):return len(self.events)<12
    def execute(self,*args):self.events.append({});self.characters+=2;return '{}'
    def validate_references(self,refs):return not refs

def response(model,action,count=100,out=20):
    return dict(status='response',raw_response=dict(model=model,usage=dict(prompt_tokens=count,completion_tokens=out),choices=[dict(finish_reason='stop',message=dict(content=json.dumps(action,separators=(',',':'))))]))

class PreparationTests(unittest.TestCase):
    def test_duplicate_fields_and_nonfinite_json_rejected(self):
        for value in ['{"x":1,"x":2}','{"x":NaN}']:
            with self.assertRaises(ValueError):strict_json(value)

    def test_shared_model_process_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            with model_lock('synthetic',tmp):
                with self.assertRaises(OSError):
                    with model_lock('synthetic',tmp):pass
            with model_lock('synthetic',tmp):pass

    def test_guard_allows_only_two_exact_public_files(self):
        import subprocess,sys
        script='''import sys,json
sys.path[:0]=[sys.argv[1]]
from chapter2_knowledge_input_guard import install
from pathlib import Path
root=Path(sys.argv[2]);files=[root/p/'model/questions.json' for p in ('open','objective')]
install(public_question_files=files)
for p in files:p.read_bytes()
blocked=0
for p in [root/'binding.json',root/'open/scoring/annotations.json',root/'open/review/records.json']:
 try:p.read_bytes()
 except PermissionError:blocked+=1
print(json.dumps(dict(allowed=2,blocked=blocked)))
'''
        result=subprocess.run([sys.executable,'-c',script,str(Path(__file__).resolve().parents[1]/'retrieval_method'),str(hr.DATASET)],check=True,capture_output=True,text=True)
        self.assertEqual(json.loads(result.stdout),dict(allowed=2,blocked=3))

    def test_no_unapproved_cumulative_token_cap(self):
        class Mock:
            calls=0
            def complete(self,body,path):
                self.calls+=1
                a=dict(action='tool',name='search',arguments=dict(query='synthetic')) if self.calls<13 else dict(action='final',answer='done',references=[])
                return response('synthetic',a,30000,1500)
        c=Mock();r=run_question(dict(question='synthetic'),'agentic','bm25','L',Tools(),c,SimpleNamespace(logical_model='llama3.1-8b',model='synthetic'),lambda _:30000)
        self.assertEqual(r['status'],'answered');self.assertEqual(c.calls,13)
        self.assertEqual(r['counted_input_tokens'],390000);self.assertEqual(r['completion_tokens'],19500)

    def test_tokenizer_mismatch_stops(self):
        c=SimpleNamespace(complete=lambda *args:response('synthetic',dict(action='final',answer='x',references=[]),101))
        r=run_question(dict(question='synthetic'),'direct','direct',None,Tools(),c,SimpleNamespace(logical_model='llama3.1-8b',model='synthetic'),lambda _:100)
        self.assertEqual(r['status'],'tokenizer_mismatch');self.assertEqual(len(r['turns']),1)

    def test_direct_does_not_load_corpus(self):
        with patch('runtime.cached',side_effect=AssertionError('External resource access')):
            t=tools_for('direct','direct',None)
        self.assertIsNone(t.corpus);self.assertFalse(t.available)

    def test_empty_reasoning_envelope_only(self):
        self.assertEqual(action_content('<think>\n\n</think>\n{}'),'{}')
        self.assertTrue(action_content('<think>nonempty</think>{}').startswith('<think>'))

    def test_basic_tools_are_registered(self):
        t=tools_for('basic','agentic','S')
        c=SimpleNamespace(complete=lambda *args:response('synthetic',dict(action='final',answer='done',references=[])))
        r=run_question(dict(question='synthetic'),'agentic','basic','S',t,c,SimpleNamespace(logical_model='llama3.1-8b',model='synthetic'),lambda _:100)
        self.assertEqual(r['status'],'answered')

    def test_structured_objective_answer_is_authoritative(self):
        q=dict(id='synthetic',type='fill');g=dict(answer='7',numeric=True)
        self.assertEqual(score(q,g,dict(status='answered',answer='explanation says 7',final_answer='8'))['score'],0)
        self.assertEqual(score(q,g,dict(status='answered',answer='explanation says 8',final_answer='7'))['score'],1)
        self.assertEqual(score(q,g,dict(status='answered',answer='FINAL:7\nmore explanation'))['score'],0)
        self.assertEqual(score(q,g,dict(status='outcome_unknown'))['score_bounds'],[0,1])
        self.assertIsNone(score(q,g,dict(status='not_run'))['score'])

    def test_formal_gate_stops_before_client(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'execution.json';p.write_bytes(encoded(dict(formal_generation_authorized=False)))
            with patch('runner.AUTHORIZATION',p),patch('runner.Client',side_effect=AssertionError('Client created')):
                with self.assertRaises(PermissionError):authorize_dispatch()

    def test_panel_authorization_cannot_start_all_tasks(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'execution.json';p.write_bytes(encoded(dict(formal_generation_authorized=True,allowed_stages=['calibration'])))
            with patch('runner.AUTHORIZATION',p):
                with self.assertRaises(PermissionError):authorize_dispatch('all')

    def test_claims_never_resubmit_and_terminal_results_skip(self):
        task=dict(task_id='synthetic',model='synthetic');client=SimpleNamespace(halted=SimpleNamespace(is_set=lambda:False))
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)/'synthetic';folder.mkdir();(folder/'claim.json').write_text('{}','utf-8')
            with self.assertRaises(RuntimeError):run_one(task,{},client,None,None,Path(tmp),'binding')
            (folder/'result.json').write_bytes(encoded(dict(task=task,protocol_sha256='binding',status='answered')))
            self.assertEqual(run_one(task,{},client,None,None,Path(tmp),'binding'),'already_terminal')
            with self.assertRaises(ValueError):run_one(task,{},client,None,None,Path(tmp),'different')

    def test_uncertain_transport_has_one_attempt_and_halts_model(self):
        d=Deployment('llama3.1-8b','synthetic','http://invalid.example/v1/chat/completions','synthetic',1)
        c=Client(d);calls=[]
        def fail(*args,**kwargs):calls.append(1);raise TimeoutError()
        c.opener=SimpleNamespace(open=fail);body=payload(d,[dict(role='user',content='synthetic')],10)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'00.json';r=c.complete(body,path)
            self.assertEqual(r['status'],'outcome_unknown');self.assertEqual(len(calls),1);self.assertTrue(c.halted.is_set())
            with self.assertRaises(FileExistsError):c.complete(body,path)
            self.assertEqual(c.complete(body)['status'],'deployment_halted');self.assertEqual(len(calls),1)

    def test_human_plan_and_empty_label_rejection(self):
        self.assertTrue(hr.verify_plan())
        with self.assertRaises(ValueError):hr.validate_labels(hr.ROOT/'calibration/blank_labels.json','calibration')
        with self.assertRaises(ValueError):hr.validate_labels(hr.ROOT/'acceptance/blank_labels.json','acceptance')

    def test_bound_human_labels_and_packet_tampering(self):
        # All fabricated values stay exclusively in a temporary test directory.
        import shutil
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'synthetic_review';shutil.copytree(hr.ROOT,root)
            with patch.object(hr,'ROOT',root):
                path=root/'calibration/packets.json';p=hr.read(path);labels=hr.read(root/'calibration/blank_labels.json')
                for packet,label in zip(p['samples'],labels['labels']):
                    packet.update(answer='synthetic test response',answer_sha256='synthetic',binding_status='bound',generation_failed=False)
                    label.update(reviewer='SYNTHETIC_UNIT_TEST_ONLY',reviewed_utc='2026-11-03T00:00:00Z',packet_sha256=hr.digest(packet))
                    r=label['record'];r.update(status='complete',fact_gate=1,applicability_gate=1 if packet['conditional'] else 'not_applicable')
                    for point in r['points']:point['score']=1
                path.write_bytes(encoded(p));lp=root/'synthetic_labels.json';lp.write_bytes(encoded(labels))
                self.assertEqual(hr.validate_labels(lp,'calibration')['complete'],60)
                p['samples'][0]['criteria'][0]['claim']='tampered';path.write_bytes(encoded(p))
                with self.assertRaises(ValueError):hr.validate_labels(lp,'calibration')

if __name__=='__main__':unittest.main()
