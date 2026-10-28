"""Operational regressions; synthetic inputs only, no API or Test score reads."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import test160_live as live
import test160_report as report
from judge_contract import calculate


class StatisticsTests(unittest.TestCase):
    def test_failure_zero_and_unknown_are_distinct(self):
        unknown=calculate([None],None,'not_applicable',False)
        failed=calculate([None],None,'not_applicable',False,True)
        self.assertIsNone(unknown['EAS_arith'])
        self.assertEqual(unknown['eas_arith_bounds'],[0,100])
        self.assertEqual(failed['EAS_arith'],0)
        self.assertEqual(failed['eas_arith_bounds'],[0,0])

    def test_question_weighting_and_dependence(self):
        ids=['a','b','c'];mapping={'a':'g1','b':'g1','c':'g2'}
        out=report.bootstrap([(0,0),(0,0),(90,90)],ids,mapping,1000)
        self.assertEqual(out['mean'],30)
        self.assertEqual(out['equal_cluster_macro_bounds'],[45,45])
        self.assertEqual(out['clusters'],2)
        unknown=report.bootstrap([(0,0),(0,100),(90,90)],ids,mapping,1000)
        self.assertIsNone(unknown['mean'])
        self.assertIsNone(unknown['ci95'])
        self.assertAlmostEqual(unknown['bounds'][1],190/3)

    def test_exact_cluster_sign_flips(self):
        ids=['a','b'];mapping=dict(a='one',b='two')
        self.assertEqual(report.signflip([1,2],ids,mapping)['p'],.25)
        self.assertEqual(report.signflip([1,2],ids,mapping,True)['p'],.5)
        self.assertEqual(report.signflip([0,0],ids,mapping)['p'],1)

    def test_degenerate_unknown_bounds_do_not_invent_point_estimate(self):
        out=report.bootstrap([(0,0)],['a'],{'a':'cluster'},100,point_identified=False)
        self.assertEqual(out['bounds'],[0,0])
        self.assertIsNone(out['mean'])
        self.assertIsNone(out['ci95'])

    def test_unknown_hypothesis_keeps_holm_denominator(self):
        rows=[dict(p=.02),dict(p=None),dict(p=.2)]
        report.holm(rows)
        self.assertEqual(rows[0]['planned_family_size'],3)
        self.assertAlmostEqual(rows[0]['holm_adjusted_p'],.06)
        self.assertFalse(rows[0]['reject'])
        self.assertIsNone(rows[1]['holm_adjusted_p'])


class TransportTests(unittest.TestCase):
    def setUp(self):
        live.VERIFIED.clear();live.BLOCKED.clear()

    def test_only_definite_transient_http_is_retried_with_unchanged_payload(self):
        body=dict(model='qwen3-14b',messages=[dict(role='user',content='fixture')],max_tokens=2048)
        saved=deepcopy(body);calls=[]
        def factory(folder,model):
            def client(payload,turn):
                calls.append((str(folder),deepcopy(payload),turn))
                return dict(status='http_rejected',http_status=503) if len(calls)==1 else dict(status='response',raw_response={})
            return client
        with tempfile.TemporaryDirectory() as tmp,patch.object(live,'ORIGINAL_CLIENT',factory),patch.object(live,'event'),patch.object(live.time,'sleep'):
            out=live.guarded_client(Path(tmp),'qwen3-14b')(body,0)
        self.assertEqual(out['status'],'response');self.assertEqual(len(calls),2)
        self.assertEqual(body,saved);self.assertEqual(calls[0][1],calls[1][1])
        self.assertNotEqual(calls[0][0],calls[1][0])

    def test_uncertain_transport_is_never_retried(self):
        calls=[]
        def factory(folder,model):
            def client(body,turn):
                calls.append(turn);return dict(status='transport_error',error_type='TimeoutError')
            return client
        with tempfile.TemporaryDirectory() as tmp,patch.object(live,'ORIGINAL_CLIENT',factory),patch.object(live,'event'):
            self.assertEqual(live.guarded_client(Path(tmp),'qwen3-8b')({},0)['status'],'transport_error')
        self.assertEqual(calls,[0])

    def test_identity_error_isolates_only_affected_model(self):
        def factory(folder,model):
            return lambda body,turn:dict(status='model_identity_mismatch' if model=='qwen3-8b' else 'response',raw_response={})
        with tempfile.TemporaryDirectory() as tmp,patch.object(live,'BASE',Path(tmp)),patch.object(live,'ORIGINAL_CLIENT',factory),patch.object(live,'event'):
            client=live.guarded_client(Path(tmp),'qwen3-8b');client({},0)
            with self.assertRaises(live.BranchBlocked):client({},1)
            self.assertEqual(live.guarded_client(Path(tmp),'qwen3-14b')({},0)['status'],'response')
            self.assertTrue((Path(tmp)/'STOP_qwen3-8b.json').exists())


if __name__=='__main__':unittest.main()
