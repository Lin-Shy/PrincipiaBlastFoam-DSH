"""Bounded source-alias matching and soft README-to-case scope priors."""
from collections import defaultdict
import re

from candidate_graph_utils import tokens
from chapter2_knowledge_graph_v5 import FocusedEvidenceGraph


def chinese_terms(text):
    return {t for t in tokens(text) if not t.isascii()}


def alias_relevance(query, query_terms, aliases):
    """Forward fields only; short generic Chinese overlap has no bonus."""
    best = 0.
    for alias in aliases:
        words = chinese_terms(alias)
        overlap = words & query_terms
        if not words or not overlap:
            continue
        exact = bool(re.search(r'[\u4e00-\u9fff]{3,}', alias)) and alias in query
        # Two adjacent bigrams (at least three characters) or an exact phrase
        # are needed; the evidence need not repeat a long question verbatim.
        if exact:
            best = 1.
        elif len(overlap) >= 2:
            coverage = len(overlap)/len(words)
            if coverage >= .5:
                best = max(best, .7*coverage)
    return best


class BilingualScopeGraph(FocusedEvidenceGraph):
    def __init__(self, *args, semantic_policy='unit', **kwargs):
        if semantic_policy not in {'unit', 'case'}:
            raise ValueError('Unknown source alias policy')
        super().__init__(*args, policy='adaptive', **kwargs)
        self.semantic_policy = semantic_policy
        self.source_aliases = {}
        self.case_source_aliases = defaultdict(set)
        for node in self.nodes.values():
            if node['kind'] != 'original_unit' or not node.get('alias_grounding'):
                continue
            self.source_aliases[node['unit_id']] = tuple(node.get('aliases', []))
            unit = self.graph['units'][node['unit_id']]
            case = unit.get('source_context', {}).get('case_directory')
            if case and unit['path'].lower().endswith('/readme.md'):
                self.case_source_aliases[case].update(node.get('aliases', []))

    def _facet_flat(self, query):
        flat = super()._facet_flat(query)
        query_terms = chinese_terms(query)
        semantic = {uid:alias_relevance(query, query_terms, aliases)
            for uid, aliases in self.source_aliases.items()}
        explicit_cases, _, _ = self._scope(query)
        cases = {}
        if self.semantic_policy == 'case' and not explicit_cases:
            cases = {case:alias_relevance(query, query_terms, aliases)
                for case, aliases in self.case_source_aliases.items()}
        for row in flat['items']:
            unit = self.graph['units'][self.nodes[row['node_id']]['unit_id']]
            own = semantic.get(unit['id'], 0)
            scope = cases.get(unit.get('source_context', {}).get('case_directory'), 0)
            row['score'] += 8*own + 8*scope
            row['reasons']['source_alias_bonus'] = 8*own
            row['reasons']['soft_case_source_alias_bonus'] = 8*scope
        flat['items'].sort(key=lambda r:(-r['score'], r['node_id']))
        flat['diagnostic']['seeds'] = flat['items'][:self.options['seed_limit']]
        flat['diagnostic'].update(bilingual_policy=self.semantic_policy,
            semantic_case_scope='soft prior, no inferred alias can exclude a case',
            source_owned_alias_units=len(self.source_aliases))
        return flat
