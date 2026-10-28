"""Finite Dev scoring, post-audit authorization and ranking regression checks."""
import json
from pathlib import Path
import tempfile
import unittest
from copy import deepcopy
from unittest.mock import patch

import scoring as core
import dev40_scoring as scoring
import dev40_analysis as analysis
import dev40_optimization as dev
from judge_contract import VERSION


class DevScoringTests(unittest.TestCase):
    def test_recovery_requires_completed_single_attempt_and_unchanged_evidence(self):
        from dev40_recovery import active_recovery
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);core.write(root/'old.json',dict(status='transport_error'));core.write(root/'new.json',dict(status='answered'))
            receipt=dict(status='started',config_id='qwen3_8b__direct__no_tools',question_id='E17-02',maximum_physical_requests=1,
                baseline_file='old.json',baseline_sha256=core.sha(root/'old.json'),result_file='new.json',result_sha256=core.sha(root/'new.json'))
            core.write(root/'infrastructure_recovery.json',receipt);self.assertIsNone(active_recovery(root))
            receipt['status']='completed';core.write(root/'infrastructure_recovery.json',receipt);self.assertEqual(active_recovery(root),receipt)
            core.write(root/'old.json',dict(status='answered'))
            with self.assertRaisesRegex(ValueError,'evidence binding changed'):active_recovery(root)

    def test_recovery_rejects_different_question_or_additional_attempts(self):
        from dev40_recovery import active_recovery
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for field,value in [('question_id','E17-03'),('maximum_physical_requests',2)]:
                receipt=dict(status='completed',config_id='qwen3_8b__direct__no_tools',question_id='E17-02',maximum_physical_requests=1)
                receipt[field]=value;core.write(root/'infrastructure_recovery.json',receipt)
                with self.assertRaisesRegex(ValueError,'Unapproved recovery scope'):active_recovery(root)

    def test_endpoint_migration_retains_original_binding_and_rejects_other_changes(self):
        import dev40_runner as runner
        old=dict(created_utc='old',source_sha256='old-source',combined_tokens=32768,concurrency={'qwen3_8b':8})
        new=dict(old,created_utc='now',source_sha256='new-source')
        receipt=dict(original_source_sha256='old-source',active_source_sha256='new-source')
        original=deepcopy(old);runner.bind_execution(new,old,receipt)
        self.assertEqual(old,original)
        for field,value in [('combined_tokens',65536),('concurrency',{'qwen3_8b':20})]:
            with self.assertRaisesRegex(ValueError,'execution binding changed'):
                runner.bind_execution(dict(new,**{field:value}),old,receipt)
        with self.assertRaisesRegex(ValueError,'source mismatch'):
            runner.bind_execution(dict(new,source_sha256='unreviewed'),old,receipt)

    def test_endpoint_overlay_changes_only_8b_and_preserves_frozen_matrix(self):
        import dev40_runner as runner
        configs=[dict(model_key='qwen3_8b',api_model_id='Qwen3-8B',endpoint='old',budget=32768),
                 dict(model_key='qwen3_14b',api_model_id='qwen3-14b',endpoint='proxy',budget=32768)]
        original=deepcopy(configs)
        with patch.object(runner,'endpoint_migration',return_value=dict(model_key='qwen3_8b',old_endpoint='old',new_endpoint='new')):
            active=runner.effective_configurations(configs)
            self.assertEqual(active[0],dict(configs[0],endpoint='new'));self.assertEqual(active[1],configs[1])
            self.assertEqual(configs,original)
            configs[0]['api_model_id']='substitute'
            with self.assertRaisesRegex(ValueError,'configuration mismatch'):runner.effective_configurations(configs)

    def test_score_requires_authorized_external_endpoint_before_network(self):
        with patch.object(scoring,'guard_operational',return_value={}),patch.object(scoring,'prepare',return_value={'private':[]}):
            with self.assertRaisesRegex(PermissionError,'configured external endpoint'):scoring.score()

    def test_operational_authorization_does_not_convert_failed_audit(self):
        with tempfile.TemporaryDirectory() as temp,patch.object(core,'ROOT',Path(temp)),patch.object(scoring,'guard_audit',return_value={'freeze':{'freeze_id':'frozen'}}):
            acceptance=core.ROOT/'audit/results/acceptance.json';core.write(acceptance,dict(accepted=False))
            authority=dict(dev40_scoring_authorized=True,test160_authorized=False,freeze_id='frozen',original_audit_acceptance_sha256=core.sha(acceptance))
            core.write(core.ROOT/'operational_use.json',authority)
            self.assertEqual(scoring.guard_operational(),authority)
            self.assertFalse(core.read(acceptance)['accepted'])
            core.write(acceptance,dict(accepted=True))
            with self.assertRaisesRegex(ValueError,'Original audit decision changed'):scoring.guard_operational()

    def test_adjacent_exact_and_unknown_have_explicit_denominators(self):
        result=analysis.adjacent_agreement([(1,.75),(.25,.25),(0,.5),('unknown',1)])
        self.assertEqual(result['n'],3);self.assertEqual(result['unknown_pairs'],1)
        self.assertAlmostEqual(result['exact'],1/3);self.assertAlmostEqual(result['within_one_level'],2/3)
        self.assertEqual(result['more_than_one_level'],1)

    def test_rank_correlation_uses_ties_and_detects_reversal(self):
        same=analysis.rank_agreement([3,3,1],[6,6,2]);self.assertAlmostEqual(same['spearman'],1);self.assertAlmostEqual(same['kendall_tau_b'],1)
        opposite=analysis.rank_agreement([3,2,1],[1,2,3]);self.assertAlmostEqual(opposite['spearman'],-1);self.assertAlmostEqual(opposite['kendall_tau_b'],-1)
        constant=analysis.rank_agreement([1,1],[2,3]);self.assertIsNone(constant['spearman']);self.assertIsNone(constant['kendall_tau_b'])

    def test_failed_generation_zero_and_ungraded_unknown_remain_distinct(self):
        item=dict(criteria=[dict(criterion_id='K001')],conditional=False,generation_failed=False)
        unknown=scoring.answer_metrics(item,None);self.assertIsNone(unknown['EAS_arith']);self.assertEqual(unknown['eas_geo_bounds'],[0,100])
        failed=scoring.answer_metrics(dict(item,generation_failed=True),None);self.assertEqual(failed['EAS_arith'],0);self.assertEqual(failed['EAS_geo'],0)

    def test_authorized_14b_selection_requires_real_complete_observations(self):
        with tempfile.TemporaryDirectory() as temp,patch.object(dev,'ROOT',Path(temp)),patch('scoring_review.guard_audit',return_value=dict(status='audit_complete',reliability_accepted=False)),patch('dev40_scoring.guard_operational',return_value=dict(dev40_parameter_selection_authorized=True)):
            source=core.DEFAULT_RUN/'experiments/agentic/dev40'
            for name in ('candidate_matrix.json','shortlist.json'):(dev.ROOT/name).write_bytes((source/name).read_bytes())
            matrix=core.read(dev.ROOT/'candidate_matrix.json');active=set(core.read(dev.ROOT/'shortlist.json')['active_configuration_ids'])
            configs=[c for c in matrix['configurations'] if c['config_id'] in active and c['model_key']=='qwen3_14b']
            rows=[]
            for c in configs:
                for q in core.read(dev.QUESTIONS):
                    rows.append(dict(schema_version=VERSION,config_id=c['config_id'],question_id=q['id'],generation_failed=False,generation_present=True,judges_complete=True,
                        judge_eas_arith_bounds={j:[50,50] for j in core.JUDGES},judge_eas_geo_bounds={j:[50,50] for j in core.JUDGES}))
            file=dev.ROOT/'results.json';out=dev.ROOT/'selected.json';core.write(file,rows)
            dev.select(file,out,'qwen3_14b');selected=core.read(out)
            self.assertFalse(selected['original_audit_passed']);self.assertTrue(selected['post_audit_operational_authorization_used']);self.assertEqual(selected['models'],['qwen3_14b'])
            self.assertEqual(len(selected['metrics']['EAS_geo']['rankings']),13)
            rows[0]['judges_complete']=False;core.write(file,rows)
            with self.assertRaisesRegex(ValueError,'two independent judge observations'):dev.select(file,out,'qwen3_14b')


if __name__=='__main__':unittest.main()
