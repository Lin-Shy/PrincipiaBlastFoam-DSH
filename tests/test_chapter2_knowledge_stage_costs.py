import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from chapter2_knowledge_stage_costs import reconcile, event_rows


class StageCostTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory(); self.addCleanup(self.tmp.cleanup); self.root = Path(self.tmp.name)

    def record(self, relative, events, model='qwen3-14b', body_hash=None):
        body = {'model': model, 'messages': [{'role': 'user', 'content': 'sample'}]}
        fingerprint = hashlib.sha256(json.dumps(body, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
        value = {'request': body, 'request_sha256': fingerprint if body_hash is None else body_hash,
            'status': 'response', 'events': events}
        if model != 'deepseek-flash': value['endpoint'] = 'https://registered.example/v1/chat/completions'
        path = self.root / relative; path.parent.mkdir(parents=True, exist_ok=True); path.write_text(json.dumps(value), encoding='utf-8')

    def event(self, start=1, attempt=1, known=True):
        return {'attempt': attempt, 'started_unix': start, 'status': 'response' if known else 'http_error',
            'seconds': 2, 'usage': {'prompt_tokens': 10, 'completion_tokens': 3} if known else None}

    def test_response_copies_reused_and_same_body_new_call_counted(self):
        self.record('development/score_calibration_009/requests/a.json', [self.event()])
        self.record('development/score_calibration_011/requests/a.json', [self.event()])
        self.record('development/score_calibration_012/requests/a.json', [self.event(start=2)])
        r = reconcile(self.root)
        self.assertEqual(r['grand_total']['physical_attempts'], 2); self.assertEqual(r['grand_total']['known_total_tokens'], 26)
        self.assertEqual(r['duplicate_physical_events_not_recharged'], 1)
        self.assertEqual(len(r['physical_event_snapshot']), 2)
        self.assertEqual({r['started_unix'] for r in r['physical_event_snapshot']}, {1, 2})
        self.assertTrue(all(set(r['event']) == {'status', 'seconds', 'usage'} for r in r['physical_event_snapshot']))

    def test_recovery_copied_prefix_preserves_original_stage(self):
        self.record('development/pilot_matrix_001/requests/a.json', [self.event(known=False)])
        self.record('audit/transport_recovery_001/requests/a.json', [self.event(known=False), self.event(start=2, attempt=2)])
        r = reconcile(self.root)
        self.assertEqual(r['stages']['main_method_development']['usage_unknown_attempts'], 1)
        self.assertEqual(r['stages']['connectivity_diagnostics']['known_total_tokens'], 13)
        self.assertEqual(r['grand_total']['usage_unknown_attempts'], 1)

    def test_capacity_probe_and_derived_availability_copy_count_once(self):
        self.record('audit/transport_capacity_probe_014b_001/requests/01.json', [self.event()])
        self.record('audit/transport_recovery_014b_capacity_001/requests/00.json', [self.event()])
        r = reconcile(self.root)
        self.assertEqual(r['request_record_files'], 2)
        self.assertEqual(r['grand_total']['physical_attempts'], 1)
        self.assertEqual(r['stages']['connectivity_diagnostics']['known_total_tokens'], 13)
        self.assertEqual(r['duplicate_physical_events_not_recharged'], 1)
        self.assertEqual(r['physical_event_snapshot'][0]['subphase'], 'audit/transport_capacity_probe_014b_001')

    def test_capacity_copy_conflict_rejected_instead_of_silently_deduplicated(self):
        self.record('audit/transport_capacity_probe_014b_001/requests/01.json', [self.event()])
        changed = self.event(); changed['usage']['completion_tokens'] = 4
        self.record('audit/transport_recovery_014b_capacity_001/requests/00.json', [changed])
        with self.assertRaisesRegex(ValueError, 'conflicting'):
            reconcile(self.root)

    def test_unresolved_start_does_not_invent_zero_duration_or_usage(self):
        self.record('development/score_calibration_001/requests/a.json', [self.event(), {'attempt': 2, 'started_unix': 2, 'status': 'in_flight'}])
        r = reconcile(self.root)['grand_total']
        self.assertEqual(r['physical_attempts'], 2); self.assertEqual(r['usage_unknown_attempts'], 1)
        self.assertEqual(r['unresolved_attempt_starts'], 1); self.assertEqual(r['duration_unknown_attempts'], 1)
        self.assertEqual(r['sum_known_physical_request_seconds'], 2)

    def test_terminal_copy_can_resolve_stale_in_flight(self):
        self.record('development/score_calibration_009/requests/a.json', [{'attempt': 1, 'started_unix': 1, 'status': 'in_flight'}])
        self.record('development/score_calibration_011/requests/a.json', [self.event()])
        r = reconcile(self.root)['grand_total']
        self.assertEqual(r['physical_attempts'], 1); self.assertEqual(r['unresolved_attempt_starts'], 0)
        self.assertEqual(r['known_total_tokens'], 13)

    def test_conflicting_event_copies_and_body_hash_drift_rejected(self):
        self.record('development/score_calibration_009/requests/a.json', [self.event()])
        e = self.event(); e['usage']['prompt_tokens'] = 11
        self.record('development/score_calibration_011/requests/a.json', [e])
        with self.assertRaisesRegex(ValueError, 'conflicting'): reconcile(self.root)
        self.record('development/score_calibration_011/requests/a.json', [self.event()], body_hash='bad')
        with self.assertRaisesRegex(ValueError, 'hash mismatch'): reconcile(self.root)

    def test_offline_legacy_endpoint_and_stage_borders(self):
        self.record('authoring/source_scoped_001/responses/a.json', [self.event()], model='deepseek-flash')
        r = reconcile(self.root)
        self.assertEqual(r['stages']['dataset_design']['known_total_tokens'], 13)
        self.assertTrue(r['request_bindings'][0]['endpoint_inferred_from_fixed_offline_client'])
        self.record('setup/unclassified/responses/a.json', [self.event(start=2)])
        with self.assertRaisesRegex(ValueError, 'unclassified'): reconcile(self.root)

    def test_formal_score_directory_and_legacy_grading_share_cost_stage(self):
        self.record('formal_scores/main/qwen3-14b_graph/r01/requests/a.json', [self.event()])
        self.record('formal_grading/main/qwen3-14b_graph/r01/requests/a.json', [self.event()])
        self.record('formal_generation/cells/main/qwen3-14b_graph/r01/requests/a.json', [self.event(start=2)])
        r = reconcile(self.root)
        self.assertEqual(r['stages']['formal_primary_grading']['physical_attempts'], 1)
        self.assertEqual(r['stages']['formal_generation']['physical_attempts'], 1)
        self.assertEqual(r['grand_total']['known_total_tokens'], 26)
        self.assertEqual(r['duplicate_physical_events_not_recharged'], 1)

    def test_gold_reviews_and_prior_cost_reports_are_not_opened(self):
        self.record('formal_scores/main/requests/a.json', [self.event()])
        for relative in ('setup/sampling/evaluation_only/gold.json',
                         'formal_original_review/pack_010/partial.json',
                         'formal_citation_review/pack_015/source-opinions.json',
                         'formal_analysis/quality.json', 'audit/stage_costs_002/report.json',
                         'formal_scores/main/sessions/Q1/score.json',
                         'formal_generation/cells/main/sessions/Q1/result.json'):
            p = self.root / relative
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text('must not parse this private file', encoding='utf-8')
        r = reconcile(self.root)
        self.assertEqual(r['request_record_files'], 1)
        self.assertFalse(r['gold_and_source_or_score_opinion_files_opened'])

    def test_live_replacement_does_not_mix_parsed_event_and_later_hash(self):
        relative = 'formal_scores/main/requests/a.json'
        self.record(relative, [self.event()])
        path = self.root / relative
        original = path.read_bytes()
        original_read = Path.read_bytes
        def replace_after_read(actual):
            result = original_read(actual)
            if actual == path:
                actual.write_text('replaced after capture', encoding='utf-8')
            return result
        with patch.object(Path, 'read_bytes', replace_after_read):
            row = event_rows(path, self.root)
        self.assertEqual(row['sha256'], hashlib.sha256(original).hexdigest())
        self.assertEqual(row['events'][0][1]['usage']['prompt_tokens'], 10)

    def test_local_write_failure_snapshot_is_not_read_or_recharged(self):
        self.record('formal_scores/main/requests/01.json', [self.event()])
        copied = 'audit/local_request_replace_stop_001/original-files/formal_scores/main/requests/01.json'
        self.record(copied, [{'attempt': 1, 'started_unix': 1, 'status': 'in_flight'}])
        snapshot = self.root / copied
        original_read = Path.read_bytes
        def reject_snapshot_read(path):
            if path == snapshot:
                raise AssertionError('forensic snapshot must be excluded before reading')
            return original_read(path)
        with patch.object(Path, 'read_bytes', reject_snapshot_read):
            result = reconcile(self.root)
        self.assertEqual(result['request_record_files'], 1)
        self.assertEqual(result['grand_total']['physical_attempts'], 1)
        self.assertEqual(result['grand_total']['known_total_tokens'], 13)
        self.assertEqual(result['grand_total']['usage_unknown_attempts'], 0)

    def test_incomplete_forensic_json_does_not_hide_real_unknown_probe_usage(self):
        self.record('formal_scores/main/requests/01.json', [self.event()])
        self.record('audit/registered8_availability_036/requests/00.json',
                    [self.event(start=i, attempt=i, known=False) for i in (2, 3, 4)], model='qwen3-8b')
        snapshot = self.root / 'audit/local_request_replace_stop_002/original-files/setup/responses/incomplete.json'
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        snapshot.write_text('incomplete forensic bytes; must not parse', encoding='utf-8')
        result = reconcile(self.root)
        self.assertEqual(result['request_record_files'], 2)
        self.assertEqual(result['grand_total']['physical_attempts'], 4)
        self.assertEqual(result['grand_total']['known_total_tokens'], 13)
        self.assertEqual(result['grand_total']['usage_unknown_attempts'], 3)
        self.assertEqual(result['stages']['connectivity_diagnostics']['physical_attempts'], 3)


if __name__ == '__main__': unittest.main()
