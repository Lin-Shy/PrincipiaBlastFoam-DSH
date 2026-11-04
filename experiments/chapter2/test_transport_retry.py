"""Transport fault injection: no remote calls, real durable request records."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError
import io, json, tempfile, unittest
from models import Client, Deployment, encoded, sha, public_deployment, payload
from transport_retry import RetryingClient, RetryPolicy, import_request, request_lock,storage_path
from runtime import run_question, tools_for
from runner import run_one

class RetryTests(unittest.TestCase):
    def setUp(self):
        self.d=Deployment('llama3.1-8b','synthetic','http://invalid.example/v1/chat/completions','SECRET_TEST_ONLY',8)
        self.body=payload(self.d,[dict(role='user',content='synthetic')],2048)
        self.raw=json.dumps(dict(model='synthetic',usage=dict(prompt_tokens=100,completion_tokens=10),choices=[dict(finish_reason='stop',message=dict(content='{"action":"final","answer":"ok","references":[]}'))])).encode()
        self.calls=[];self.delays=[]

    def factory(self,sequence):
        def factory(d,timeout):
            self.assertEqual(timeout,600)
            c=Client(d,timeout=timeout)
            def opened(*a,**k):
                self.calls.append(a[0].data);item=sequence.pop(0)
                if isinstance(item,BaseException):raise item
                class Reply:
                    status=200
                    def __enter__(self):return self
                    def __exit__(self,*a):pass
                    def read(self):return item
                return Reply()
            c.opener=SimpleNamespace(open=opened);return c
        return factory

    def client(self,sequence):return RetryingClient(self.d,sleeper=self.delays.append,factory=self.factory(sequence))

    def test_timeout_then_success_reuses_identical_request_and_preserves_both(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'00.json';c=self.client([TimeoutError(),self.raw]);r=c.complete(self.body,p)
            self.assertEqual(r['status'],'response');self.assertFalse(c.halted.is_set())
            self.assertEqual(len(self.calls),2);self.assertEqual(self.calls[0],self.calls[1]);self.assertEqual(self.delays,[5])
            self.assertEqual([x['status'] for x in r['attempts']],['outcome_unknown','response'])
            for x in r['attempts']:self.assertEqual(sha((p.parent/x['record_file']).read_bytes()),x['record_sha256'])
            self.assertEqual(p.with_suffix('.response.bin').read_bytes(),self.raw)
            self.assertNotIn('SECRET_TEST_ONLY',p.read_text('utf-8'))
            c.complete(self.body,p);self.assertEqual(len(self.calls),2)

    def test_bounded_exhaustion_and_restart_do_not_reset_attempt_count(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'00.json';c=self.client([TimeoutError()]*3);r=c.complete(self.body,p)
            self.assertEqual(len(self.calls),3);self.assertEqual(self.delays,[5,15]);self.assertTrue(r['retry_exhausted']);self.assertTrue(c.halted.is_set())
            self.client([]).complete(self.body,p);self.assertEqual(len(self.calls),3)

    def test_transient_http_retry_and_permanent_rejection(self):
        for status,expected in [(408,2),(429,2),(502,2),(401,1),(400,1)]:
            with self.subTest(status=status),tempfile.TemporaryDirectory() as tmp:
                before=len(self.calls);error=HTTPError('http://invalid.example',status,'synthetic',{},io.BytesIO(b'{}'))
                self.client([error,self.raw]).complete(self.body,Path(tmp)/'00.json')
                self.assertEqual(len(self.calls)-before,expected)

    def test_received_bad_answer_or_truncation_never_content_retried(self):
        for content,finish in [('not JSON','stop'),(' ','stop'),('{','length')]:
            raw=json.dumps(dict(model='synthetic',usage=dict(prompt_tokens=100,completion_tokens=10),choices=[dict(finish_reason=finish,message=dict(content=content))])).encode()
            with self.subTest(content=content),tempfile.TemporaryDirectory() as tmp:
                c=self.client([raw]);before=len(self.calls)
                r=run_question(dict(question='synthetic'),'direct','direct',None,tools_for('direct','direct',None),c,self.d,lambda _:100,Path(tmp))
                self.assertIn(r['status'],{'invalid_action','completion_truncated'});self.assertEqual(len(self.calls)-before,1)

    def test_interrupted_attempt_is_charged_and_immutable(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'00.json';folder=p.parent/'attempts/00';folder.mkdir(parents=True)
            row=dict(deployment=public_deployment(self.d),request=self.body,request_sha256=sha(encoded(self.body)),status='in_flight',transport_attempts=0)
            original=encoded(row);(folder/'000.json').write_bytes(original)
            r=self.client([self.raw]).complete(self.body,p)
            self.assertEqual(r['transport_attempts'],2);self.assertIsNone(r['attempts'][0]['transmitted'])
            self.assertEqual((folder/'000.json').read_bytes(),original);self.assertEqual(len(self.calls),1)

    def test_crash_after_received_response_recovers_without_post(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'00.json';original_factory=self.factory([self.raw])
            def crashing(d,timeout):
                c=original_factory(d,timeout);complete=c.complete
                def saved_then_crashed(*a):complete(*a);raise KeyboardInterrupt()
                c.complete=saved_then_crashed;return c
            c=RetryingClient(self.d,factory=crashing,sleeper=self.delays.append)
            with self.assertRaises(KeyboardInterrupt):c.complete(self.body,p)
            self.assertEqual(self.client([]).complete(self.body,p)['status'],'response');self.assertEqual(len(self.calls),1)

    def test_imported_timeout_counts_as_original_attempt_and_prefix_cannot_drift(self):
        with tempfile.TemporaryDirectory() as tmp:
            old=Path(tmp)/'original/00.json';old.parent.mkdir();legacy=Client(self.d);legacy.opener=SimpleNamespace(open=lambda *a,**k:(_ for _ in ()).throw(TimeoutError()))
            legacy.complete(self.body,old);old_bytes=old.read_bytes();target=Path(tmp)/'recovery/00.json';import_request(old,target)
            r=self.client([self.raw]).complete(self.body,target)
            self.assertEqual(r['transport_attempts'],2);self.assertEqual(r['attempts'][0]['origin'],'imported')
            self.assertEqual(old.read_bytes(),old_bytes);import_request(old,target)
            different=dict(self.body,max_tokens=1)
            with self.assertRaises(ValueError):self.client([]).complete(different,target)
            self.assertEqual(len(self.calls),1)

    def test_interrupted_task_claim_resumes_and_completed_task_is_not_repeated(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);t=dict(task_id='synthetic',model='llama3.1-8b',part='open',id='q',method='direct',mode='direct',budget=None)
            folder=root/'synthetic';folder.mkdir();(folder/'claim.json').write_bytes(encoded(dict(task=t,protocol_sha256='p')))
            c=self.client([self.raw]);questions={'open':{'q':dict(question='synthetic')}}
            self.assertEqual(run_one(t,questions,c,lambda _:100,self.d,root,'p'),'answered')
            self.assertEqual(run_one(t,questions,c,lambda _:100,self.d,root,'p'),'already_terminal');self.assertEqual(len(self.calls),1)
            self.assertEqual(len(list((folder/'resumes').glob('*.json'))),1)

    def test_live_request_owner_is_not_mistaken_for_interruption(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'00.json'
            with request_lock(p):
                with self.assertRaises(OSError):self.client([]).complete(self.body,p)
            self.assertEqual(len(self.calls),0)

    def test_invalid_policy_and_undurable_retry_rejected(self):
        for kwargs in [dict(max_attempts=0),dict(timeout_seconds=0),dict(backoff_seconds=())]:
            with self.assertRaises(ValueError):RetryPolicy(**kwargs)
        with self.assertRaises(ValueError):self.client([]).complete(self.body)

    def test_local_response_save_error_is_not_retried_and_bytes_are_preserved(self):
        import base64
        original_open=Path.open
        def opened(p,*a,**k):
            if p.name.endswith('.response.bin'):raise FileNotFoundError('synthetic local path failure')
            return original_open(p,*a,**k)
        with tempfile.TemporaryDirectory() as tmp,patch.object(Path,'open',opened):
            c=self.client([self.raw]);r=c.complete(self.body,Path(tmp)/'00.json')
            self.assertEqual(r['status'],'runner_error');self.assertEqual(r['infrastructure_cause'],'response_persistence_error');self.assertEqual(len(self.calls),1)
            self.assertEqual(base64.b64decode(r['response_body_base64']),self.raw);self.assertTrue(c.halted.is_set())
            from objective_scoring import score
            self.assertIsNone(score(dict(id='synthetic',type='fill'),dict(answer='7'),r)['score'])

    def test_recovery_wire_paths_fit_windows_legacy_limit(self):
        from recover_transport import recovery_root,task_folder
        for model in ('qwen3-8b','qwen3-14b','llama3.1-8b'):
            p=task_folder(recovery_root('a'*64)/model,'b'*64)/'requests/attempts/12/002.response.bin'
            self.assertLess(len(str(p)),240)

    def test_actual_long_request_and_response_paths(self):
        # The extended temp root also lets standard TemporaryDirectory cleanup
        # address the generated deep files on Windows.
        with tempfile.TemporaryDirectory(dir=str(storage_path(tempfile.gettempdir()))) as tmp:
            p=Path(tmp)/('a'*100)/('b'*100)/'requests/00.json'
            r=self.client([self.raw]).complete(self.body,p)
            self.assertEqual(r['status'],'response')
            self.assertEqual(storage_path(p.with_suffix('.response.bin')).read_bytes(),self.raw)

    def test_preparation_does_not_reset_an_active_retry_budget(self):
        import recover_transport as recovery
        with tempfile.TemporaryDirectory() as tmp:
            pointer=Path(tmp)/'pointer.json';pointer.write_bytes(encoded(dict(overlay_sha256='existing')))
            gate=Path(tmp)/'gate.json';gate.write_bytes(encoded(dict(formal_generation_authorized=False,allowed_stages=[],transport_recovery_authorized=True)))
            with patch.object(recovery,'POINTER',pointer),patch.object(recovery,'GATE',gate):
                with self.assertRaisesRegex(ValueError,'explicit --revise'):recovery.prepare_overlay()
                with self.assertRaisesRegex(ValueError,'recovery is active'):recovery.prepare_overlay(revise=True)

if __name__=='__main__':unittest.main()
