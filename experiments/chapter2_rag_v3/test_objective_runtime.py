"""Offline isolated tests for objective run resume, unknown holds, and retries."""
import json
import tempfile
import types
import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch
import objective_experiment as exp

class RuntimeTests(unittest.TestCase):
    def test_duplicate_start_is_blocked_by_exclusive_lock(self):
        from central_execution import exclusive_lock
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2]/'.local') as tmp:
            path=Path(tmp)/'lane.lock'
            with exclusive_lock(path):
                with self.assertRaises(FileExistsError):
                    with exclusive_lock(path):pass
            self.assertFalse(path.exists())

    def test_resume_unknown_hold_and_retry_limit(self):
        calls=[];events=[];makes=[]
        configs=[dict(config_id='c'+str(i),model_key='qwen3_8b',method_id='direct',logical_model='qwen3-8b') for i in range(13)]
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[2]/'.local') as tmp:
            root=Path(tmp); manifest=root/'manifest.json';manifest.write_text('{}')
            qs=[dict(id='Q1',question='fixture',type='fill')]
            m=dict(question_file='questions.json',configurations=configs,deployments={'qwen3_8b':{'v':1}})
            # One existing result must be reused; one uncertain prior request must remain held.
            done=root/'generation/c0/Q1/result.json';done.parent.mkdir(parents=True);done.write_text('{"existing":true}')
            unknown=root/'generation/c1/Q1/requests';unknown.mkdir(parents=True)
            class Session:
                delivered_lines=set()
            class Agent:
                def __init__(self,model,session,client,count,budget):self.client=client
                def run(self,question):
                    reply=self.client({'messages':[],'max_tokens':1},0)
                    return {'status':'answered','answer':'FINAL: x','reply_status':reply['status']}
            class Budget:
                def __init__(self,**kw):pass
            class Registry:
                def resolve(self,key):return {'v':1}
            def fake_client(folder):
                def call(body,turn):
                    calls.append(str(folder))
                    # Initial response and both permitted retries all fail: no fourth attempt.
                    return {'status':'response','http_status':503}
                return call
            central=types.ModuleType('central_execution');central.Registry=Registry;central.exclusive_lock=lambda p:nullcontext()
            transport=types.ModuleType('dev40_supplement')
            live=types.ModuleType('test160_live');live.extend_local_timeout=lambda:None
            agent=types.ModuleType('principia_core.retrieval.knowledge_agent');agent.AutonomousKnowledgeAgent=Agent;agent.ModelBudget=Budget
            interface=types.ModuleType('chapter2_common_qa_interface');interface.neutral_messages=lambda m:m
            deployment=types.ModuleType('chapter2_qa_deployment');deployment.prepared_messages=lambda m,c:m;deployment.ANSWER_CHECKLIST=''
            modules={'central_execution':central,'dev40_supplement':transport,'test160_live':live,
                     'principia_core.retrieval.knowledge_agent':agent,'chapter2_common_qa_interface':interface,
                     'chapter2_qa_deployment':deployment}
            tokenizer=types.SimpleNamespace(apply_chat_template=lambda *a,**kw:[])
            def make_tools(c,folder):makes.append(c['config_id']);return Session()
            def read(path):return qs if Path(path).name=='questions.json' else json.loads(Path(path).read_text())
            with patch.dict('sys.modules',modules),patch.object(exp,'OUT',root),patch.object(exp,'WORK',root),patch.object(exp,'MANIFEST',manifest),\
                 patch.object(exp,'verify',return_value=m),patch.object(exp,'read',side_effect=read),patch.object(exp,'generation_guard'),\
                 patch.object(exp,'initialize_runtime',return_value=(make_tools,None,tokenizer)),patch.object(exp,'supercomputer_deployment',return_value={'v':1}),\
                 patch.object(exp,'supercomputer_client',side_effect=fake_client),patch.object(exp,'event',side_effect=lambda **kw:events.append(kw)),\
                 patch.object(exp.time,'sleep'):
                exp.run(model='qwen3_8b',workers=1)
                self.assertEqual(len(calls),11*3)
                self.assertEqual(len(makes),11)
                self.assertTrue(any(e['kind']=='unknown_hold' and e['config']=='c1' for e in events))
                self.assertEqual(json.loads(done.read_text()),{'existing':True})
                exp.run(model='qwen3_8b',workers=1)
                self.assertEqual(len(calls),11*3)
                self.assertEqual(len(list((root/'generation').rglob('result.json'))),12)

if __name__=='__main__':unittest.main()
