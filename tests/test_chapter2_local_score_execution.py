import copy
import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments/retrieval_method'))
from chapter2_local_score_execution import score_local_answer,request_sha,validate_local_activation
from chapter2_qwen_local import LocalModel,prepare_body


class Client:
    deployment=LocalModel('http://localhost:8001/v1/chat/completions','Qwen3-14B','not-used')
    def __init__(self,status='response',model='Qwen3-14B',prompt=100):
        self.calls=0;self.status=status;self.model=model;self.prompt=prompt
    def __call__(self,body,turn):
        self.calls+=1;body=prepare_body(body,self.deployment)
        return dict(status=self.status,request=body,request_sha256=request_sha(body),endpoint=self.deployment.endpoint,
            raw_response=dict(model=self.model,usage=dict(prompt_tokens=self.prompt,completion_tokens=10)))


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.requests=[dict(stage='coverage',body=dict(model='qwen3-14b',messages=[dict(role='user',content='candidate')],
            temperature=0,max_tokens=4096,enable_thinking=False,response_format=dict(type='json_object')))]*2
        self.client=Client()
        self.budget=dict(actual_input_tokens=[100,100],local_context_limit=16384,
            actual_request_sha256=[request_sha(prepare_body(r['body'],self.client.deployment)) for r in self.requests])
        self.parse=lambda responses,payload,requests:dict(status='judged',metrics=dict(complete_valid_answer=1,complete_lower=1,complete_upper=1))
    def run_score(self,**kwargs):
        args=dict(result=dict(status='answered'),payload={},requests=self.requests,client=self.client,budget=self.budget,
                  count_tokens=lambda messages:100,parse=self.parse)
        args.update(kwargs);return score_local_answer(**args)
    def test_success_uses_actual_bodies(self):
        score=self.run_score();self.assertEqual(score['metrics']['complete_valid_answer'],1)
        self.assertEqual(self.client.calls,2);self.assertEqual(score['counted_input_tokens'],200)
    def test_generation_failure_has_zero_calls_and_observed_zero(self):
        score=self.run_score(result=dict(status='generation_error'),requests=[],budget=dict(actual_input_tokens=[],actual_request_sha256=[]))
        self.assertEqual(score['metrics']['complete_upper'],0);self.assertEqual(self.client.calls,0)
    def test_capacity_overflow_keeps_unknown_without_calls(self):
        self.budget['actual_input_tokens']=[12289,12289]
        score=self.run_score(count_tokens=lambda messages:12289)
        self.assertEqual(score['reason'],'local_deployment_context_exceeded')
        self.assertIsNone(score['metrics']['complete_valid_answer']);self.assertEqual(self.client.calls,0)
    def test_exact_capacity_boundary_permits_request(self):
        self.budget['actual_input_tokens']=[12288,12288];self.client.prompt=12288
        self.assertEqual(self.run_score(count_tokens=lambda messages:12288)['status'],'judged')
    def test_request_drift_rejected_before_network(self):
        self.budget['actual_request_sha256'][0]='changed'
        with self.assertRaises(ValueError):self.run_score()
        self.assertEqual(self.client.calls,0)
    def test_prompt_count_drift_stops_with_unknown(self):
        self.client.prompt=101
        self.assertEqual(self.run_score()['reason'],'local_prompt_token_count_mismatch')
        self.assertEqual(self.client.calls,1)
    def test_model_mismatch_is_not_relabelled(self):
        self.client.model='qwen3-14b'
        self.assertEqual(self.run_score()['reason'],'judge_model_mismatch');self.assertEqual(self.client.calls,1)
    def test_transport_failure_stops_remaining_stages(self):
        self.client.status='transport_error';score=self.run_score()
        self.assertTrue(score['transport_circuit_open']);self.assertEqual(self.client.calls,1)
    def test_format_failure_is_not_quality_retried(self):
        self.client.status='invalid_response'
        score=self.run_score(parse=lambda *args:dict(status='judge_unknown',reason='invalid_response'))
        self.assertEqual(score['metrics']['complete_upper'],1);self.assertEqual(self.client.calls,2)
    def test_partial_known_failure_is_kept(self):
        score=self.run_score(parse=lambda *args:dict(status='partially_judged',reason='later_unknown',
            metrics=dict(complete_valid_answer=0,complete_lower=0,complete_upper=0)))
        self.assertEqual(score['status'],'partially_judged');self.assertEqual(score['metrics']['complete_upper'],0)
    def test_registration_gate_rejects_missing_and_partial_evidence(self):
        with self.assertRaises(ValueError):validate_local_activation({}, {}, {}, {})
        activation=dict(schema='uniform_local_judge_activation_v1',scope='full_fixed_13536_answers',
                        context_overflow_policy='retain_unknown_without_truncation')
        calibration=dict(numeric_thresholds_passed=True,overall=dict(controls=42))
        semantic=dict(schema='local_judge_development_semantic_acceptance_v1',accepted=True,
                      reviewed_control_count=42,pending_controls=[],human_truth=False)
        budget=dict(sessions=13536,rows=[{}]*13536,fixed_output_cap=4096,answers_truncated=False)
        self.assertTrue(validate_local_activation(activation,calibration,semantic,budget))
        for changes in [dict(sessions=13535),dict(fixed_output_cap=2048),dict(answers_truncated=True)]:
            with self.assertRaises(ValueError):validate_local_activation(activation,calibration,semantic,{**budget,**changes})
        with self.assertRaises(ValueError):validate_local_activation(activation,calibration,{**semantic,'pending_controls':['one']},budget)


if __name__=='__main__':unittest.main()
