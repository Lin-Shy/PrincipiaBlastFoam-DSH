import copy
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments/retrieval_method'))
from chapter2_qwen_compact_grammar import compact_grammar_requests
from chapter2_qwen_local import LocalModel,prepare_body
from chapter2_local_compact_score_execution import score_local_answer,request_sha,validate_local_activation


class StructuredExecutionTests(unittest.TestCase):
    def setUp(self):
        body=dict(model='qwen3-14b',messages=[dict(role='user',content=json.dumps(dict(premise_segments=[dict(id='A1')],hypothesis='claim')))],
                  temperature=0,max_tokens=4096,enable_thinking=False,response_format=dict(type='json_object'))
        self.requests=compact_grammar_requests([dict(stage='source_free_coverage',point_id='K1',body=body)])
        class Client:
            deployment=LocalModel('http://localhost:8001/v1/chat/completions','Qwen3-14B','unused')
            calls=0
            def __call__(self,body,index):
                self.calls+=1;actual=prepare_body(body,self.deployment)
                return dict(status='response',request=actual,request_sha256=request_sha(actual),endpoint=self.deployment.endpoint,
                    raw_response=dict(model=self.deployment.model,usage=dict(prompt_tokens=100,completion_tokens=10)))
        self.client=Client()
        self.budget=dict(actual_input_tokens=[100],local_context_limit=16384,response_schema_policy='candidate_segments_compact_grammar_hard_nonthinking_v1')
        self.bind()
    def bind(self):
        self.budget['actual_request_sha256']=[request_sha(prepare_body(r['body'],self.client.deployment)) for r in self.requests]
    def run_score(self,parse=None):
        parse=parse or (lambda *args:dict(status='judged',metrics=dict(complete_valid_answer=0,complete_lower=0,complete_upper=0)))
        return score_local_answer(dict(status='answered'),{},self.requests,self.client,self.budget,lambda _:100,parse)
    def test_negative_judgment_preserved(self):
        self.assertEqual(self.run_score()['metrics']['complete_valid_answer'],0);self.assertEqual(self.client.calls,1)
    def test_schema_cannot_force_positive_verdict_even_with_new_hash(self):
        self.requests[0]['body']['structured_outputs']['grammar']='root ::= "full"'
        self.bind()
        with self.assertRaises(ValueError):self.run_score()
        self.assertEqual(self.client.calls,0)
    def test_schema_cannot_invent_candidate_ids_even_with_new_hash(self):
        self.requests[0]['body']['structured_outputs']['grammar']=self.requests[0]['body']['structured_outputs']['grammar'].replace('A1','A999')
        self.bind()
        with self.assertRaises(ValueError):self.run_score()
        self.assertEqual(self.client.calls,0)
    def test_legacy_format_does_not_silently_enter_structured_run(self):
        self.requests[0]['body']['response_format']={'type':'json_object'};self.bind()
        with self.assertRaises(ValueError):self.run_score()
    def test_template_mode_cannot_drift(self):
        self.requests[0]['body']['chat_template_kwargs']={'enable_thinking':True};self.bind()
        with self.assertRaises(ValueError):self.run_score()
        self.assertEqual(self.client.calls,0)
    def test_registered_schema_policy_required(self):
        self.budget.pop('response_schema_policy')
        with self.assertRaises(ValueError):self.run_score()
        self.assertEqual(self.client.calls,0)
    def test_unknown_remains_unknown(self):
        result=self.run_score(lambda *args:dict(status='judge_unknown',reason='semantic_or_schema_unknown'))
        self.assertIsNone(result['metrics']['complete_valid_answer']);self.assertEqual(result['metrics']['complete_upper'],1)
    def test_synthetic_control_success_cannot_replace_actual_answer_audit(self):
        activation=dict(schema='uniform_local_judge_activation_v1',scope='full_fixed_13536_answers',
            response_schema_policy='candidate_segments_compact_grammar_hard_nonthinking_v1',
            context_overflow_policy='retain_unknown_without_truncation')
        calibration=dict(numeric_thresholds_passed=True,overall=dict(controls=42))
        semantic=dict(schema='local_judge_development_semantic_acceptance_v1',accepted=True,
            reviewed_control_count=42,pending_controls=[],human_truth=False)
        budget=dict(sessions=13536,rows=[{}]*13536,fixed_output_cap=4096,answers_truncated=False)
        with self.assertRaises(ValueError):validate_local_activation(activation,calibration,semantic,budget)
        semantic['actual_development_audit']=dict(planned_answers=15,reviewed_answers=15,pending_answers=[],
            accepted=True,method_labels_masked=True,automatic_labels_replaced=False,report_sha256='a'*64)
        self.assertTrue(validate_local_activation(activation,calibration,semantic,budget))
        semantic['actual_development_audit']['reviewed_answers']=14
        with self.assertRaises(ValueError):validate_local_activation(activation,calibration,semantic,budget)


if __name__=='__main__':unittest.main()
