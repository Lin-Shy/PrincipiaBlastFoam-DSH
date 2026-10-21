import copy
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'experiments/retrieval_method'))
from chapter2_qwen_structured_output import constrain_requests


class StructuredTests(unittest.TestCase):
    def requests(self,conditional=True):
        values=[('source_free_coverage',dict(premise_segments=[dict(id='A1'),dict(id='A2')],hypothesis='target')),
            ('independent_original_truth_audit',dict(candidate_segments=[dict(id='A1'),dict(id='A2')],condition_required=conditional))]
        return [dict(stage=stage,body=dict(model='qwen3-14b',messages=[dict(role='user',content=json.dumps(value))],
            temperature=0,max_tokens=4096,response_format=dict(type='json_object'))) for stage,value in values]
    def test_only_response_format_changes(self):
        source=self.requests();snapshot=copy.deepcopy(source);result=constrain_requests(source)
        self.assertEqual(source,snapshot)
        for before,after in zip(source,result):
            actual=copy.deepcopy(after);actual['body']['response_format']=before['body']['response_format']
            self.assertEqual(actual,before)
    def test_coverage_keeps_all_semantic_choices_and_actual_ids(self):
        schema=constrain_requests(self.requests())[0]['body']['response_format']['json_schema']['schema']
        self.assertEqual(set(schema['properties']['verdict']['enum']),{'full','partial','missing','wrong','unknown'})
        self.assertEqual(schema['properties']['answer_segment_ids']['items']['enum'],['A1','A2'])
        self.assertFalse(schema['additionalProperties'])
    def test_audit_requires_each_actual_segment_once_in_order(self):
        schema=constrain_requests(self.requests())[1]['body']['response_format']['json_schema']['schema']
        segments=schema['properties']['segments']
        self.assertEqual((segments['minItems'],segments['maxItems']),(2,2))
        self.assertEqual([s['properties']['id']['const'] for s in segments['prefixItems']],['A1','A2'])
        self.assertEqual(set(schema['required']),{'segments','condition'})
        self.assertNotIn('not_applicable',schema['properties']['condition']['properties']['verdict']['enum'])
    def test_nonconditional_fix_matches_existing_deterministic_label(self):
        schema=constrain_requests(self.requests(False))[1]['body']['response_format']['json_schema']['schema']
        self.assertEqual(schema['properties']['condition']['properties']['verdict']['enum'],['not_applicable'])
    def test_unknown_stage_and_duplicate_ids_rejected(self):
        requests=self.requests();requests[0]['stage']='unexpected'
        with self.assertRaises(ValueError):constrain_requests(requests)
        requests=self.requests();value=json.loads(requests[1]['body']['messages'][0]['content']);value['candidate_segments'][1]['id']='A1'
        requests[1]['body']['messages'][0]['content']=json.dumps(value)
        with self.assertRaises(ValueError):constrain_requests(requests)


if __name__=='__main__':unittest.main()
