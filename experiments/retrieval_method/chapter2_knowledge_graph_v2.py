"""Development candidate: typed propagation and compact original evidence.

No QA labels, embeddings, BM25, inverted index, or learned query weights.
The original v1 implementation and frozen artifacts remain unchanged.
"""
from collections import defaultdict
import re
import time

from chapter2_knowledge_graph_retriever import KnowledgeGraphRetriever, terms, condition_text, case_directory, present
from candidate_graph_utils import tokens

PLATFORM_WORDS = {'blastfoam', 'openfoam'}
ENGLISH_STOP = {'a','an','the','of','to','and','in','for','is','on','with','as','from','or','if','it','this','that','be','by'}

# Source-supported semantic relations only. Physical containment is already
# available through source ownership; expanding it as relevance causes hubs.
RELATION_DECAY = {
    'DOCUMENTED_BY': .90, 'PARAMETER_CONTEXT': .90,
    'DESCRIBES': .85, 'PARAMETER_OF': .85,
    'REQUIRES': .85, 'CONFLICTS_WITH': .80,
    'SAME_PUBLIC_IDENTITY': .90, 'EXPLAINS': .80,
    'SELECTS_MODEL': .85, 'CONSUMES_FIELD': .70, 'PRODUCES_FIELD': .70,
    'SOURCE_SECTION_PARENT': .60,
    'FILE_SELECTOR_CONTEXT': .90,
}


class EvidenceGraphV2(KnowledgeGraphRetriever):
    def __init__(self, *args, evidence_policy='compact', **kwargs):
        if evidence_policy not in {'compact', 'whole'}:
            raise ValueError('Unknown original evidence policy')
        super().__init__(*args, **kwargs)
        self.evidence_policy = evidence_policy

    def _facet_flat(self, query):
        """Scan graph text for technical identifiers; no fitted term statistics.

        Platform names are scope context, not distinctive search identities.
        Complete identifiers carry twice the weight of their camel-case parts.
        Chinese aliases remain a separate matching channel, avoiding dilution
        of a precise parameter name by a long natural-language question.
        """
        distinctive = re.sub(r'(?<![A-Za-z0-9_])(?:blastfoam|openfoam)(?![A-Za-z0-9_])',' ',query,flags=re.I)
        identifiers = {v.casefold() for v in re.findall(r'[A-Za-z_][A-Za-z0-9_]*',distinctive)} - PLATFORM_WORDS - ENGLISH_STOP
        qt = set(tokens(distinctive)) - PLATFORM_WORDS - ENGLISH_STOP
        english = {t for t in qt if t.isascii()} | identifiers
        chinese = qt - english
        weights = {t: 2 if t in identifiers else 1 for t in english}
        cases = [p for p in self.cases if present(query,p.split('/')[-1]) or p in query]
        manual_only = '手册' in query and '教程' not in query and not cases
        tutorial_only = '只查教程' in query or '仅查教程' in query
        ranked, scanned, filtered, navigation = [], 0, 0, 0
        for nid,node in self.nodes.items():
            case = self.case_paths.get(node['path'])
            if ((cases and case and case not in cases) or
                (manual_only and node['path'].startswith('tutorials/')) or
                (tutorial_only and node['path'].startswith('manual/'))):
                filtered += 1
                continue
            if node.get('dictionary','').startswith('FoamFile'):
                continue
            unit = self.graph['units'][node['unit_id']]
            headings = [c['title'] for c in unit.get('context',[])]
            if any(re.fullmatch(r'(?:table of )?contents|目录',h.strip(),re.I) for h in headings):
                navigation += 1
                continue
            text = ' '.join(str(node.get(k) or '') for k in ('label','name','subject','owner_model','key','value','dictionary','body'))
            text += ' ' + ' '.join(node.get('aliases',[]))
            scanned += len(text)
            nt = set(tokens(text))
            context_terms = set(tokens(' '.join(headings)))
            hits = english & nt
            context_hits = english & context_terms
            cn = chinese & nt
            # Original relative paths help resolve explicit case/file context,
            # but a filename match alone cannot supply semantic answer content.
            path_match = bool(set(tokens(node['path'])) & identifiers)
            if not hits and not context_hits and not cn and not path_match:
                continue
            lexical = 30 * sum(weights[t] for t in hits)/max(1,sum(weights.values()))
            lexical += 8 * len(cn)/max(1,len(chinese))
            lexical += 8 * sum(weights[t] for t in context_hits)/max(1,sum(weights.values()))
            identity = str(node.get('name') or node.get('owner_model') or '').casefold()
            key = str(node.get('key') or '').casefold()
            score = lexical + 4 * bool(identity and identity in identifiers) + 4 * bool(key and key in identifiers)
            score += 2 * path_match + 4 * (case in cases if case else False)
            conditions = condition_text(node.get('conditions',[])) if self.options['with_conditions'] else ''
            condition_overlap = len(qt & set(tokens(conditions)))
            score += min(2,condition_overlap)
            ranked.append(dict(node_id=nid,score=score,origin=nid,visited=[nid],route=[],
                reasons=dict(technical_identifier_overlap=sorted(hits),chinese_overlap=len(cn),
                    source_heading_overlap=sorted(context_hits),
                    exact_identity_match=identity in identifiers,condition_overlap=condition_overlap)))
        ranked.sort(key=lambda r:(-r['score'],r['node_id']))
        return dict(items=ranked,diagnostic=dict(seeds=ranked[:self.options['seed_limit']],
            graph_field_characters_scanned=scanned,scope_filtered_nodes=filtered,
            navigation_only_nodes_excluded=navigation,
            external_index_loaded=False,model_calls=0,rank_is_before_character_budget=True,
            source_owners=len({n['owner'] for n in self.nodes.values()}),
            seed_policy='separate_technical_identifiers_and_chinese_aliases_v2'))

    def rank(self, query):
        started = time.monotonic()
        enabled = self.options['with_paths']
        flat = self._facet_flat(query)
        seeds = flat['diagnostic']['seeds']
        best = {r['node_id']: dict(r) for r in flat['items']}
        frontier = seeds
        expanded = 0
        qt = terms(query)
        cases = [p for p in self.cases if present(query, p.split('/')[-1]) or p in query]
        if enabled:
            for _ in range(self.options['depth']):
                following = []
                for row in frontier:
                    for target, edge, direction in self.adjacency[row['node_id']]:
                        decay = RELATION_DECAY.get(edge['relation'])
                        if decay is None or target in row['visited']:
                            continue
                        if edge['relation'] == 'FILE_SELECTOR_CONTEXT' and direction != 'forward':
                            continue
                        node = self.nodes[target]
                        # Flat rankings applied the scope policy. Nodes outside
                        # the native pool still need the same explicit filter.
                        case = case_directory(node['path'])
                        if cases and case and case not in cases:
                            continue
                        if '手册' in query and '教程' not in query and not cases and node['path'].startswith('tutorials/'):
                            continue
                        if ('只查教程' in query or '仅查教程' in query) and node['path'].startswith('manual/'):
                            continue
                        # A section's parent is structural context, not a license
                        # to traverse every sibling section of the whole manual.
                        if edge['relation'] == 'SOURCE_SECTION_PARENT':
                            if not qt & terms(' '.join(str(node.get(k) or '') for k in ('label', 'name', 'body'))):
                                continue
                        expanded += 1
                        score = row['score'] * decay
                        route = row['route'] + [{
                            'edge_id': edge['id'], 'relation': edge['relation'],
                            'direction': direction, 'cross_owner': edge['cross_owner'],
                            'conditions': edge.get('conditions', []), 'condition_evaluated': False,
                        }]
                        candidate = dict(node_id=target, score=score, origin=row['origin'],
                            visited=row['visited'] + [target], route=route,
                            reasons={'typed_route': True, 'decay': decay})
                        if target not in best or score > best[target]['score']:
                            best[target] = candidate
                            following.append(candidate)
                frontier = sorted(following, key=lambda r: (-r['score'], r['node_id']))[:self.options['seed_limit']]
        # Deduplicate source units BEFORE spending ranking slots on diversity.
        # This prevents many semantic nodes from one section occupying top-10.
        units = {}
        for row in best.values():
            uid = self.nodes[row['node_id']]['unit_id']
            if uid not in units or (row['score'], row['node_id']) > (units[uid]['score'], units[uid]['node_id']):
                units[uid] = row
        candidates = list(units.values())
        native, path_counts = [], defaultdict(int)
        while candidates and len(native) < self.options['native_limit']:
            row = min(candidates, key=lambda r: (-r['score'] / (1 + .25 * path_counts[self.nodes[r['node_id']]['path']]), r['node_id']))
            candidates.remove(row)
            node = self.nodes[row['node_id']]
            path_counts[node['path']] += 1
            native.append({**row, 'native_rank': len(native) + 1, 'path': node['path'],
                'owner': node['owner'], 'anchors': node['evidence'],
                'conditions': node.get('conditions', []) if self.options['with_conditions'] else []})
        return dict(schema='typed_evidence_graph_ranking_v2_development', items=native,
            options=dict(self.options), graph_sha256=self.graph_sha256,
            diagnostic={**flat['diagnostic'], 'seeds': seeds, 'expanded_edges': expanded,
                'graph_scan_seconds_and_ranking': time.monotonic() - started,
                'cross_owner_additive_bonus': 0, 'ranked_unique_source_units': len(units),
                'evidence_policy': self.evidence_policy})

    def read_native(self, ranking):
        if self.evidence_policy == 'whole':
            return super().read_native(ranking)
        items = []
        for row in ranking['items']:
            node = self.nodes[row['node_id']]
            unit = self.graph['units'][node['unit_id']]
            anchors = node['evidence']
            start = min(a['start'] for a in anchors)
            end = max(a['end'] for a in anchors)
            # Small original sections remain complete. Long units are centered
            # on the actual source quote, retaining four lines on both sides.
            # The agent can read the rest with the common read_source tool.
            if len(unit['text']) <= 1600:
                start, end = unit['start'], unit['end']
            else:
                start, end = max(unit['start'], start - 4), min(unit['end'], end + 4)
            items.append(dict(path=node['path'], ranges=[dict(start=start, end=end)],
                native_unit=row['node_id'], native_rank=row['native_rank'], owner=row['owner'],
                original_sha256=unit['sha256'], read_policy='source_quote_and_original_context',
                owning_original_fragment=dict(start=unit['start'], end=unit['end'])))
        return dict(items=items, ranking_diagnostic=ranking['diagnostic'], native_ranking=ranking)
