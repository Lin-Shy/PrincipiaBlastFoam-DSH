"""Offline synthetic checks: these are never human calibration or experiment data."""
import json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from matrix import configurations,tasks
from models import MODELS,payload
from runtime import run_question,tools_for
from judge_contract import calculate

class CurrentTests(unittest.TestCase):
    def test_matrix_identity_and_denominators(self):
        rows=list(tasks());self.assertEqual(len(list(configurations())),171)
        self.assertEqual(len(rows),51300);self.assertEqual(len({r['task_id'] for r in rows}),51300)
        for model in MODELS:
            for part,n in [('open',100),('objective',200)]:
                subset=[r for r in rows if r['model']==model and r['part']==part]
                self.assertEqual(len(subset),57*n)
                for mode in ['single_pass','agentic']:self.assertEqual(sum(r['mode']==mode for r in subset),28*n)
    def test_both_modes_and_parts_all_models(self):
        class Tools:
            method='bm25';available=True
            def __init__(self):self.events=[];self.characters=0
            def execute(self,name,args):self.events.append(dict(name=name));self.characters+=2;return '{}'
            def validate_references(self,refs):return not refs
        for model in MODELS:
            dep=SimpleNamespace(logical_model=model,model=model)
            for part in ['open','objective']:
                q=dict(question='Synthetic check',id='synthetic')
                if part=='objective':q['type']='fill'
                for mode in ['single_pass','agentic','direct']:
                    tools=Tools()
                    class Mock:
                        def __init__(self):self.calls=0
                        def complete(self,body,path):
                            self.calls+=1
                            action=dict(action='tool',name='search',arguments=dict(query='synthetic')) if mode=='agentic' and self.calls==1 else dict(action='final',answer='FINAL:x',references=[])
                            if part=='objective' and action['action']=='final':action['final_answer']='x'
                            return dict(status='response',raw_response=dict(model=model,usage=dict(prompt_tokens=100,completion_tokens=10),choices=[dict(finish_reason='stop',message=dict(content=json.dumps(action,separators=(',',':'))))]))
                    client=Mock();result=run_question(q,mode,'direct' if mode=='direct' else 'bm25','M',tools,client,dep,lambda msgs:100)
                    self.assertEqual(result['status'],'answered');self.assertEqual(len(tools.events),0 if mode=='direct' else 1)
                    self.assertEqual(client.calls,2 if mode=='agentic' else 1)
    def test_model_parameters_and_hard_context(self):
        for model in MODELS:
            dep=SimpleNamespace(logical_model=model,model=model)
            body=payload(dep,[dict(role='user',content='synthetic')],2048)
            if model=='llama3.1-8b':self.assertNotIn('enable_thinking',body);self.assertNotIn('/no_think',body['messages'][0]['content'])
        class NoCall:
            def complete(self,*args):raise AssertionError('Over-budget request sent')
        class Tools:
            method='none';available=False;characters=0;events=[]
        result=run_question(dict(question='synthetic'),'direct','direct',None,Tools(),NoCall(),SimpleNamespace(logical_model='llama3.1-8b',model='llama'),lambda msgs:32700)
        self.assertEqual(result['status'],'input_budget_exhausted')
    def test_source_backend_and_single_pass_budget(self):
        for mode in ['single_pass','agentic']:
            tools=tools_for('bm25',mode,'M')
            encoded=tools.execute('search',dict(query='JWL equationOfState'))
            self.assertLessEqual(len(encoded),12000 if mode=='single_pass' else 6000)
            self.assertEqual(tools.characters,len(encoded));self.assertTrue(json.loads(encoded))
    def test_scoring_bounds_and_failures(self):
        self.assertAlmostEqual(calculate([.25,.75],.75,1,True)['EAS_arith'],75)
        self.assertEqual(calculate([1],1,'not_applicable',False,True)['EAS_arith'],0)
        self.assertEqual(calculate(['unknown'],1,'not_applicable',False)['eas_arith_bounds'],[50,100])
    def test_graph_arms_use_current_source_only(self):
        from runtime import tools_for
        for method in ['graph','no_cross','no_aliases','no_traversal','anchor_only']:
            tools=tools_for(method,'single_pass','S')
            value=tools.execute('search',dict(query='JWL equationOfState'))
            self.assertTrue(json.loads(value));self.assertLessEqual(len(value),6000)

if __name__=='__main__':unittest.main()
