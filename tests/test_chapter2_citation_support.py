import copy
import hashlib
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from chapter2_citation_support import citation_payload, judge_body, parse_support, score_citations
from principia_core.retrieval.knowledge_qa import FrozenKnowledgeCorpus


class CitationSupportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name); path = root / 'manual/a.md'; path.parent.mkdir(); path.write_text('scalar only\nmodel separate\n', encoding='utf-8')
        manifest = root / 'manifest.json'; manifest.write_text(json.dumps({'schema': 'independent_blast_knowledge_corpus_v1',
            'files': [{'path': 'manual/a.md', 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'bytes': path.stat().st_size, 'lines': 2}]}), encoding='utf-8')
        self.corpus = FrozenKnowledgeCorpus(root, manifest)
        self.result = {'status': 'answered', 'answer': '只支持标量。模型条目独立。',
            'references': [{'path': 'manual/a.md', 'start': 1, 'end': 2}],
            'tool_events': [{'delivered_original_lines': [{'path': 'manual/a.md', 'line': 1}]},
                {'delivered_original_lines': [{'path': 'manual/a.md', 'line': 2}]}]}
        self.payload, _ = citation_payload('支持向量吗？', self.result, self.corpus)
        self.verdict = {'segments': [{'id': 'A1', 'verdict': 'supported', 'support_reference_ids': ['R1'], 'reason': 'scalar only'},
            {'id': 'A2', 'verdict': 'supported', 'support_reference_ids': ['R1'], 'reason': 'separate'}],
            'references': [{'id': 'R1', 'verdict': 'useful', 'segment_ids': ['A1', 'A2'], 'reason': 'both explicit'}]}

    def response(self, value=None, model='qwen3-14b', finish='stop'):
        return {'status': 'response', 'response': {'model': model, 'choices': [{'finish_reason': finish,
            'message': {'content': json.dumps(self.verdict if value is None else value)}}]}}

    def test_only_actual_cited_union_no_rubric(self):
        body = judge_body(self.payload); value = json.loads(body['messages'][1]['content'])
        self.assertEqual(set(value), {'question', 'candidate_answer', 'candidate_segments', 'cited_originals'})
        self.assertEqual([r['text'] for r in value['cited_originals'][0]['lines']], ['scalar only', 'model separate'])
        self.assertEqual(value['candidate_segments'][0]['text'], '只支持标量。')

    def test_duplicate_refs_do_not_inflate_denominator(self):
        r = copy.deepcopy(self.result); r['references'] *= 2
        value, status = citation_payload('问题', r, self.corpus)
        self.assertEqual(status['duplicate_references'], 1); self.assertEqual(len(value['cited_originals']), 1)

    def test_missing_delivery_and_invalid_path_never_call(self):
        for change in ('undelivered', 'path', 'coordinate'):
            r = copy.deepcopy(self.result)
            if change == 'undelivered': r['tool_events'] = []
            elif change == 'path': r['references'][0]['path'] = '../gold.json'
            else: r['references'][0]['end'] = True
            score = score_citations('问题', r, self.corpus, lambda *_: self.fail('no API permitted'), lambda _: 1)
            self.assertEqual(score['metrics']['complete_citation_support'], 0); self.assertEqual(score['model_requests'], 0)

    def test_empty_refs_and_generation_failure_known_zero(self):
        for status, refs in [('answered', []), ('transport_error', None)]:
            r = {**self.result, 'status': status, 'references': refs}
            score = score_citations('问题', r, self.corpus, lambda *_: self.fail('no API permitted'), lambda _: 1)
            self.assertEqual(score['metrics']['complete_upper'], 0)

    def test_full_supported(self):
        score = parse_support(self.response(), self.payload)
        self.assertEqual(score['metrics']['complete_citation_support'], 1)
        self.assertEqual(score['metrics']['segment_support_lower'], 1)

    def test_unknown_not_dropped_and_definite_failure_stays_zero(self):
        v = copy.deepcopy(self.verdict); v['segments'][1].update(verdict='unknown', support_reference_ids=[])
        v['references'][0]['segment_ids'] = ['A1']
        score = parse_support(self.response(v), self.payload)
        self.assertIsNone(score['metrics']['complete_citation_support'])
        self.assertEqual((score['metrics']['segment_support_lower'], score['metrics']['segment_support_upper']), (.5, 1))
        v['segments'][0]['verdict'] = 'partial'
        self.assertEqual(parse_support(self.response(v), self.payload)['metrics']['complete_citation_support'], 0)

    def test_contradiction_is_not_positive_reference_usefulness(self):
        v = copy.deepcopy(self.verdict); v['segments'][0]['verdict'] = 'contradicted'
        score = parse_support(self.response(v), self.payload)
        self.assertEqual(score['status'], 'citation_judge_unknown')
        v['references'][0]['segment_ids'] = ['A2']
        self.assertEqual(parse_support(self.response(v), self.payload)['metrics']['complete_citation_support'], 0)

    def test_invented_duplicate_missing_ids_unknown(self):
        for mode in ('invented', 'duplicate', 'missing'):
            v = copy.deepcopy(self.verdict)
            if mode == 'invented': v['segments'][0]['support_reference_ids'] = ['R2']
            elif mode == 'duplicate': v['segments'].append(v['segments'][0])
            else: v['segments'].pop()
            self.assertEqual(parse_support(self.response(v), self.payload)['status'], 'citation_judge_unknown')

    def test_transport_wrong_model_truncated_no_quality_retry(self):
        for record in ({'status': 'transport_error'}, self.response(model='other'), self.response(finish='length')):
            calls = []
            def client(body, turn): calls.append(body); return record
            score = score_citations('问题', self.result, self.corpus, client, lambda _: 100)
            self.assertEqual(len(calls), 1); self.assertEqual(score['metrics']['complete_upper'], 1)
            self.assertIsNone(score['metrics']['complete_citation_support'])

    def test_input_budget_never_calls(self):
        score = score_citations('问题', self.result, self.corpus, lambda *_: self.fail('no API permitted'), lambda _: 32769)
        self.assertEqual(score['model_requests'], 0); self.assertEqual(score['reason'], 'citation_judge_input_budget_exhausted')


if __name__ == '__main__': unittest.main()
