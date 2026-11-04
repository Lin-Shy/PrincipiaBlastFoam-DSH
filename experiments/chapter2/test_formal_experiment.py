"""Full-run recovery contracts using durable synthetic transport, no network."""
from pathlib import Path
from types import SimpleNamespace
import json
import tempfile
import unittest
from unittest.mock import patch
from models import Deployment,Client,payload
from transport_retry import RetryingClient
import formal_experiment as full


class FormalTests(unittest.TestCase):
    def setUp(self):
        self.d=Deployment('llama3.1-8b','synthetic','http://invalid.example/v1/chat/completions','SYNTHETIC_ONLY',8)
        self.body=payload(self.d,[dict(role='user',content='synthetic')],2048)
        self.raw=json.dumps(dict(model='synthetic',usage=dict(prompt_tokens=100,completion_tokens=10),choices=[dict(finish_reason='stop',message=dict(content='{"action":"final","answer":"ok","references":[]}'))])).encode()
        self.calls=[]
        self.task=dict(task_id='synthetic',id='synthetic',method='direct',mode='direct',budget=None)

    def client(self,sequence):
        def factory(d,timeout):
            client=Client(d,timeout=timeout)
            def opened(*args,**kwargs):
                self.calls.append(args[0].data);value=sequence.pop(0)
                if isinstance(value,BaseException):raise value
                class Response:
                    status=200
                    def __enter__(self):return self
                    def __exit__(self,*args):pass
                    def read(self):return value
                return Response()
            client.opener=SimpleNamespace(open=opened);return client
        return RetryingClient(self.d,concurrency=1,sleeper=lambda _:None,factory=factory)

    def engine(self,sequence,crash=False):
        def execute(q,mode,method,budget,tools,client,d,counter,folder):
            response=client.complete(self.body,folder/'00.json')
            if crash:raise KeyboardInterrupt()
            return dict(status='answered' if response['status']=='response' else response['status'],answer='ok' if response['status']=='response' else None)
        return execute

    def test_crash_after_response_replays_without_another_post_and_skips_terminal(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp)/'task'
            with self.assertRaises(KeyboardInterrupt):
                full.task_generation(self.task,{},self.d,None,folder,'protocol',client_factory=lambda:self.client([self.raw]),engine=self.engine([],True))
            value=full.task_generation(self.task,{},self.d,None,folder,'protocol',client_factory=lambda:self.client([]),engine=self.engine([]))
            self.assertEqual(value['status'],'answered');self.assertEqual(len(self.calls),1)
            def no_call():raise AssertionError('Terminal result must skip transport construction')
            self.assertEqual(full.task_generation(self.task,{},self.d,None,folder,'protocol',client_factory=no_call)['answer'],'ok')
            self.assertEqual(len(self.calls),1)
            with self.assertRaises(ValueError):full.task_generation(self.task,{},self.d,None,folder,'other-protocol',client_factory=no_call)

    def test_exhausted_task_keeps_three_attempts_and_next_task_can_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            a=full.task_generation(self.task,{},self.d,None,Path(tmp)/'a','p',client_factory=lambda:self.client([TimeoutError()]*3),engine=self.engine([]))
            self.assertEqual(a['status'],'outcome_unknown');self.assertEqual(len(self.calls),3)
            full.task_generation(self.task,{},self.d,None,Path(tmp)/'a','p',client_factory=lambda:(_ for _ in ()).throw(AssertionError('No retry reset')))
            b=full.task_generation(dict(self.task,task_id='next'),{},self.d,None,Path(tmp)/'b','p',client_factory=lambda:self.client([self.raw]),engine=self.engine([]))
            self.assertEqual(b['status'],'answered');self.assertEqual(len(self.calls),4)

    def test_unknown_generation_is_not_zero_and_failed_generation_is_zero_without_judge_API(self):
        packet=dict(sample_id='synthetic',conditional=False,criteria=[dict(criterion_id='K1')],generation_failed=False)
        profile=dict(prompt_version='current-calibration-candidate')
        def no_call():raise AssertionError('No judge API for generation failure/unknown')
        with tempfile.TemporaryDirectory() as tmp:
            unknown=full.judge_one('p',self.task,dict(status='outcome_unknown'),packet,'gpt_sol',profile,Path(tmp)/'unknown',client_factory=no_call)
            self.assertIsNone(unknown['metrics']['EAS_arith']);self.assertEqual(unknown['metrics']['eas_arith_bounds'],[0,100])
            failed=full.judge_one('p',self.task,dict(status='invalid_action'),dict(packet,generation_failed=True),'gpt_sol',profile,Path(tmp)/'failed',client_factory=no_call)
            self.assertEqual(failed['metrics']['EAS_arith'],0)

    def test_extra_acceptance_is_blocked_before_any_label_access(self):
        import human_review
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'release/planning').mkdir(parents=True)
            (root/'release/planning/review_workflow.json').write_text('{"acceptance_cancelled":true}',encoding='utf-8')
            with patch.object(human_review,'EXPERIMENT',root):
                with self.assertRaises(PermissionError):human_review.freeze('nonexistent')
                with self.assertRaises(PermissionError):human_review.bind('nonexistent','acceptance')


if __name__=='__main__':unittest.main()
